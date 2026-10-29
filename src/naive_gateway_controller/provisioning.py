"""Secret-safe controller orchestration for bootstrap and deployment."""

from __future__ import annotations

import getpass
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

from passlib.hash import sha512_crypt

from naive_gateway_controller.config import GatewaySettings
from naive_gateway_controller.errors import ControllerError, ProvisioningError
from naive_gateway_controller.preflight import (
    PreflightMode,
    PreflightReport,
    SSHProbe,
    run_preflight,
)
from naive_gateway_controller.ssh import (
    SSHAuthMethodsResult,
    SSHProbeResult,
    SSHStatus,
    probe_ssh,
    probe_ssh_auth_methods,
)
from naive_gateway_controller.tooling import (
    ansible_environment,
    check_playbook_syntax,
    project_root,
)

PasswordPrompt = Callable[[], str]
AnsibleExecutor = Callable[[Sequence[str], Mapping[str, object], Mapping[str, str]], int]
PreflightRunner = Callable[[GatewaySettings, Path], PreflightReport]


class SSHAuthProbe(Protocol):
    """Injectable authentication-method inspection boundary."""

    def __call__(
        self,
        *,
        host: str,
        port: int,
        user: str,
        identity_file: Path,
        known_hosts_file: Path,
    ) -> SSHAuthMethodsResult:
        """Inspect server-offered authentication methods."""


def prompt_sudo_password() -> str:
    """Read and confirm a sudo password without echoing it."""
    password = getpass.getpass("VPS_USER sudo password: ")
    confirmation = getpass.getpass("Confirm VPS_USER sudo password: ")
    if not password:
        raise ProvisioningError("sudo password must not be empty")
    if password != confirmation:
        raise ProvisioningError("sudo password confirmation does not match")
    return password


def hash_sudo_password(password: str) -> str:
    """Create a Linux-compatible SHA-512 crypt hash on the controller."""
    return str(sha512_crypt.using(rounds=656_000).hash(password))


def execute_ansible(
    command: Sequence[str],
    variables: Mapping[str, object],
    environment: Mapping[str, str],
) -> int:
    """Pass extra vars through an inherited pipe, never through argv or a file."""
    read_fd, write_fd = os.pipe()
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            [*command, "--extra-vars", f"@/dev/fd/{read_fd}"],
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            pass_fds=(read_fd,),
        )
        os.close(read_fd)
        read_fd = -1
        with os.fdopen(write_fd, "wb") as stream:
            write_fd = -1
            stream.write(json.dumps(variables, separators=(",", ":")).encode())
        return process.wait()
    except (BrokenPipeError, OSError) as error:
        if process is not None:
            process.wait()
        raise ProvisioningError("failed to execute the Ansible playbook") from error
    finally:
        if read_fd >= 0:
            os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)


def _ssh_common_args(known_hosts_file: Path) -> str:
    options = (
        "-4",
        "-F /dev/null",
        "-o BatchMode=yes",
        "-o IdentitiesOnly=yes",
        "-o StrictHostKeyChecking=yes",
        f"-o UserKnownHostsFile={shlex.quote(str(known_hosts_file))}",
        "-o GlobalKnownHostsFile=/dev/null",
        "-o UpdateHostKeys=no",
        "-o ControlMaster=no",
        "-o ControlPath=none",
    )
    return " ".join(options)


def prompt_current_sudo_password() -> str:
    """Read the existing managed-user password without echo or confirmation."""
    password = getpass.getpass("Current VPS_USER sudo password: ")
    if not password:
        raise ProvisioningError("sudo password must not be empty")
    return password


def prompt_bootstrap_sudo_password() -> str:
    """Allow an empty password only for a bootstrap account with NOPASSWD sudo."""
    return getpass.getpass("Bootstrap user current sudo password (empty for NOPASSWD): ")


def run_deploy(
    settings: GatewaySettings,
    *,
    root: Path | None = None,
    password_prompt: PasswordPrompt = prompt_current_sudo_password,
    preflight_runner: PreflightRunner = run_preflight,
    ansible_executor: AnsibleExecutor = execute_ansible,
) -> None:
    """Deploy only over managed SSH; all remote changes belong to Ansible."""
    root = root or project_root()
    known_hosts_file = (root / "provisioning/known_hosts").resolve()
    report = preflight_runner(settings, known_hosts_file)
    if report.mode is not PreflightMode.MANAGED:
        raise ProvisioningError("deploy requires a managed host; run make bootstrap first")
    variables: dict[str, object] = {
        "ansible_host": settings.vps_host,
        "ansible_port": settings.vps_port,
        "ansible_user": settings.vps_user,
        "ansible_ssh_private_key_file": str(settings.ssh_private_key),
        "ansible_ssh_common_args": _ssh_common_args(known_hosts_file),
        "ansible_become_password": password_prompt(),
        "docker_managed_user": settings.vps_user,
        "naive_gateway_repository": settings.gateway_repository,
        "naive_gateway_ref": settings.gateway_ref,
        "naive_gateway_domain": settings.domain,
        "naive_gateway_acme_email": settings.acme_email,
        "naive_gateway_user": settings.naive_user or "",
        "naive_gateway_password": (
            settings.naive_password.get_secret_value() if settings.naive_password else ""
        ),
    }
    command = [
        str(Path(sys.prefix) / "bin/ansible-playbook"),
        "--inventory",
        "naive_gateway,",
        str(root / "provisioning/playbooks/deploy.yml"),
    ]
    if ansible_executor(command, variables, ansible_environment(root)) != 0:
        raise ProvisioningError("deploy failed; resolve the reported stage and rerun make deploy")


def run_verify(
    settings: GatewaySettings,
    *,
    root: Path | None = None,
    password_prompt: PasswordPrompt = prompt_current_sudo_password,
    preflight_runner: PreflightRunner = run_preflight,
    ssh_probe: SSHProbe = probe_ssh,
    auth_probe: SSHAuthProbe = probe_ssh_auth_methods,
    ansible_executor: AnsibleExecutor = execute_ansible,
) -> None:
    """Check access and host/application state without changing host configuration."""
    root = root or project_root()
    known_hosts = (root / "provisioning/known_hosts").resolve()
    report = preflight_runner(settings, known_hosts)
    if report.mode is not PreflightMode.MANAGED:
        raise ProvisioningError("verification requires managed SSH; run make bootstrap")
    if _probe_key(settings, known_hosts, "root", ssh_probe).status is not SSHStatus.AUTH_FAILED:
        raise ProvisioningError("root key login was not confirmed disabled")
    if not _probe_auth(settings, known_hosts, auth_probe).password_methods_disabled:
        raise ProvisioningError("password or keyboard-interactive SSH was not confirmed disabled")
    print("DNS: PASS\nSSH access and authentication: PASS", flush=True)
    variables: dict[str, object] = {
        "ansible_host": settings.vps_host,
        "ansible_port": settings.vps_port,
        "ansible_user": settings.vps_user,
        "ansible_ssh_private_key_file": str(settings.ssh_private_key),
        "ansible_ssh_common_args": _ssh_common_args(known_hosts),
        "ansible_become_password": password_prompt(),
        "verify_user": settings.vps_user,
        "verify_ssh_port": settings.vps_port,
        "verify_domain": settings.domain,
        "verify_acme_email": settings.acme_email,
        "verify_ref": settings.gateway_ref,
        "verify_naive_user": settings.naive_user or "",
        "verify_naive_password": (
            settings.naive_password.get_secret_value() if settings.naive_password else ""
        ),
    }
    command = [
        str(Path(sys.prefix) / "bin/ansible-playbook"),
        "--inventory",
        "naive_gateway,",
        str(root / "provisioning/playbooks/verify.yml"),
    ]
    if ansible_executor(command, variables, ansible_environment(root)) != 0:
        raise ProvisioningError(
            "verification failed; inspect the failed layer and rerun make verify"
        )


def run_restore(settings: GatewaySettings, archive: Path, *, root: Path | None = None) -> None:
    """Restore application state through Ansible without fetching any source Git."""
    root = root or project_root()
    archive = archive.resolve()
    if not archive.is_file() or stat.S_IMODE(archive.stat().st_mode) != 0o600:
        raise ProvisioningError("restore requires a regular backup archive with mode 0600")
    check_playbook_syntax(root)
    known_hosts = (root / "provisioning/known_hosts").resolve()
    report = run_preflight(settings, known_hosts)
    if report.mode is not PreflightMode.MANAGED:
        raise ProvisioningError(
            "restore requires a prepared managed host; run make bootstrap first"
        )
    variables: dict[str, object] = {
        "ansible_host": settings.vps_host,
        "ansible_port": settings.vps_port,
        "ansible_user": settings.vps_user,
        "ansible_ssh_private_key_file": str(settings.ssh_private_key),
        "ansible_ssh_common_args": _ssh_common_args(known_hosts),
        "ansible_become_password": prompt_current_sudo_password(),
        "docker_managed_user": settings.vps_user,
        "restore_archive": str(archive),
        "restore_domain": settings.domain,
    }
    command = [
        str(Path(sys.prefix) / "bin/ansible-playbook"),
        "--inventory",
        "naive_gateway,",
        str(root / "provisioning/playbooks/restore.yml"),
    ]
    if execute_ansible(command, variables, ansible_environment(root)) != 0:
        raise ProvisioningError(
            "restore failed; keep the backup and inspect the empty-host/recovery requirements before retrying"
        )


def read_credentials(
    settings: GatewaySettings,
    password: str | None,
    *,
    root: Path | None = None,
    password_prompt: PasswordPrompt = prompt_current_sudo_password,
) -> tuple[str, str, str]:
    """Read runtime credentials through SSH/sudo with the password only on stdin."""
    root = root or project_root()
    known_hosts = (root / "provisioning/known_hosts").resolve()
    if not known_hosts.is_file() or stat.S_IMODE(known_hosts.stat().st_mode) != 0o600:
        raise ProvisioningError(
            "credentials require a private known_hosts file; run make preflight"
        )
    if password is None:
        password = password_prompt()
    remote_command = shlex.join(
        ["sudo", "-S", "-k", "-p", "", "/usr/bin/cat", "/etc/naive-gateway/gateway.env"],
    )
    command = [
        "ssh",
        *shlex.split(_ssh_common_args(known_hosts)),
        "-T",
        "-p",
        str(settings.vps_port),
        "-i",
        str(settings.ssh_private_key),
        f"{settings.vps_user}@{settings.vps_host}",
        remote_command,
    ]
    try:
        result = subprocess.run(
            command,
            input=f"{password}\n",
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ProvisioningError("unable to read credentials; rerun make credentials") from error
    if result.returncode != 0:
        raise ProvisioningError(
            "unable to read credentials; check SSH and sudo, then rerun make credentials"
        )
    entries = [line.split("=", 1) for line in result.stdout.splitlines()]
    if any(len(entry) != 2 for entry in entries):
        raise ProvisioningError("runtime credentials file has an invalid format")
    values = {entry[0]: entry[1] for entry in entries}
    if len(entries) != 4 or set(values) != {"DOMAIN", "ACME_EMAIL", "NAIVE_USER", "NAIVE_PASSWORD"}:
        raise ProvisioningError("runtime credentials file has an invalid format")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", values["DOMAIN"]) or any(
        re.fullmatch(r"[A-Za-z0-9._~-]+", values[key]) is None
        for key in ("NAIVE_USER", "NAIVE_PASSWORD")
    ):
        raise ProvisioningError("runtime credentials file has invalid values")
    return values["DOMAIN"], values["NAIVE_USER"], values["NAIVE_PASSWORD"]


def run_provision(settings: GatewaySettings, *, root: Path | None = None) -> str:
    """Orchestrate bootstrap, deployment and verification using one in-memory password."""
    root = root or project_root()
    check_playbook_syntax(root)
    print("Ansible syntax: PASS (bootstrap, deploy, verify, restore)", flush=True)
    known_hosts = (root / "provisioning/known_hosts").resolve()
    try:
        report = run_preflight(settings, known_hosts)
    except ControllerError as error:
        raise ProvisioningError(f"preflight failed; resume with make preflight: {error}") from error
    password = (
        prompt_sudo_password()
        if report.mode is PreflightMode.BOOTSTRAP
        else prompt_current_sudo_password()
    )
    print("Bootstrap: reconciling managed access and firewall", flush=True)
    try:
        run_bootstrap(
            settings,
            root=root,
            password_prompt=lambda: password,
            preflight_runner=lambda _settings, _known_hosts: report,
        )
    except ControllerError as error:
        raise ProvisioningError(f"bootstrap failed; resume with make bootstrap: {error}") from error
    print("Deploy: starting", flush=True)
    managed_report = PreflightReport(report.network, PreflightMode.MANAGED, report.known_host_added)

    def reuse_preflight(_settings: GatewaySettings, _known_hosts: Path) -> PreflightReport:
        return managed_report

    try:
        run_deploy(
            settings, root=root, password_prompt=lambda: password, preflight_runner=reuse_preflight
        )
    except ControllerError as error:
        raise ProvisioningError(f"deploy failed; resume with make deploy: {error}") from error
    print("Deploy: PASS\nVerification: starting", flush=True)
    try:
        run_verify(
            settings, root=root, password_prompt=lambda: password, preflight_runner=reuse_preflight
        )
    except ControllerError as error:
        raise ProvisioningError(f"verification failed; resume with make verify: {error}") from error
    return password


def _probe_key(
    settings: GatewaySettings,
    known_hosts_file: Path,
    user: str,
    ssh_probe: SSHProbe,
) -> SSHProbeResult:
    return ssh_probe(
        host=settings.vps_host,
        port=settings.vps_port,
        user=user,
        identity_file=settings.ssh_private_key,
        known_hosts_file=known_hosts_file,
    )


def _probe_auth(
    settings: GatewaySettings,
    known_hosts_file: Path,
    auth_probe: SSHAuthProbe,
) -> SSHAuthMethodsResult:
    return auth_probe(
        host=settings.vps_host,
        port=settings.vps_port,
        user=settings.vps_user,
        identity_file=settings.ssh_private_key,
        known_hosts_file=known_hosts_file,
    )


def run_bootstrap(
    settings: GatewaySettings,
    *,
    root: Path | None = None,
    password_prompt: PasswordPrompt = prompt_sudo_password,
    bootstrap_password_prompt: PasswordPrompt = prompt_bootstrap_sudo_password,
    preflight_runner: PreflightRunner = run_preflight,
    ssh_probe: SSHProbe = probe_ssh,
    auth_probe: SSHAuthProbe = probe_ssh_auth_methods,
    ansible_executor: AnsibleExecutor = execute_ansible,
) -> None:
    """Create the managed user, harden SSH, and apply the host firewall."""
    root = root or project_root()
    known_hosts_file = (root / "provisioning/known_hosts").resolve()
    preflight = preflight_runner(settings, known_hosts_file)

    root_key = _probe_key(settings, known_hosts_file, settings.vps_bootstrap_user, ssh_probe)
    apply_user_role = True
    if preflight.mode is PreflightMode.MANAGED:
        if root_key.status is SSHStatus.AUTH_FAILED:
            apply_user_role = False
        elif root_key.status is not SSHStatus.OK:
            raise ProvisioningError("cannot determine a safe SSH bootstrap recovery path")
    elif root_key.status is not SSHStatus.OK:
        raise ProvisioningError("bootstrap-user key connection failed after preflight")

    password = password_prompt()
    bootstrap_password = (
        bootstrap_password_prompt()
        if apply_user_role and settings.vps_bootstrap_user != "root"
        else ""
    )
    variables: dict[str, object] = {
        "ansible_host": settings.vps_host,
        "ansible_port": settings.vps_port,
        "ansible_ssh_private_key_file": str(settings.ssh_private_key),
        "ansible_ssh_common_args": _ssh_common_args(known_hosts_file),
        "bootstrap_become_password": bootstrap_password,
        "managed_become_password": password,
        "bootstrap_apply_user": apply_user_role,
        "bootstrap_controller_epoch": int(time.time()),
        "bootstrap_user_name": settings.vps_bootstrap_user,
        "firewall_ssh_port": settings.vps_port,
        "user_name": settings.vps_user,
        "user_password_hash": hash_sudo_password(password),
        "user_authorized_key": settings.public_key_path.read_text(encoding="utf-8").strip(),
    }
    command = [
        str(Path(sys.prefix) / "bin/ansible-playbook"),
        "--inventory",
        "naive_gateway,",
        str(root / "provisioning/playbooks/bootstrap.yml"),
    ]
    if ansible_executor(command, variables, ansible_environment(root)) != 0:
        raise ProvisioningError("bootstrap playbook failed; SSH access was not declared safe")

    managed_key = _probe_key(settings, known_hosts_file, settings.vps_user, ssh_probe)
    if managed_key.status is not SSHStatus.OK:
        raise ProvisioningError("managed-user reconnect failed after SSH hardening")
    root_key = _probe_key(settings, known_hosts_file, "root", ssh_probe)
    if root_key.status is not SSHStatus.AUTH_FAILED:
        raise ProvisioningError("root key login was not rejected after SSH hardening")
    auth_methods = _probe_auth(settings, known_hosts_file, auth_probe)
    if not auth_methods.password_methods_disabled:
        raise ProvisioningError("password or keyboard-interactive SSH remains available")
