"""Secret-safe controller orchestration for the Phase 4 bootstrap playbook."""

from __future__ import annotations

import getpass
import json
import os
import shlex
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from passlib.hash import sha512_crypt

from naive_gateway_controller.config import GatewaySettings
from naive_gateway_controller.errors import ProvisioningError
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
from naive_gateway_controller.tooling import ansible_environment, project_root

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


class BootstrapOutcome(StrEnum):
    """Stable result rendered by the CLI."""

    APPLIED = "applied"
    SKIPPED = "managed host already hardened"


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
        raise ProvisioningError("failed to execute the bootstrap playbook") from error
    finally:
        if read_fd >= 0:
            os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)


def _ssh_common_args(known_hosts_file: Path) -> str:
    options = (
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
    preflight_runner: PreflightRunner = run_preflight,
    ssh_probe: SSHProbe = probe_ssh,
    auth_probe: SSHAuthProbe = probe_ssh_auth_methods,
    ansible_executor: AnsibleExecutor = execute_ansible,
) -> BootstrapOutcome:
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
    variables: dict[str, object] = {
        "ansible_host": settings.vps_host,
        "ansible_port": settings.vps_port,
        "ansible_ssh_private_key_file": str(settings.ssh_private_key),
        "ansible_ssh_common_args": _ssh_common_args(known_hosts_file),
        "ansible_become_password": password,
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
    root_key = _probe_key(settings, known_hosts_file, settings.vps_bootstrap_user, ssh_probe)
    if root_key.status is not SSHStatus.AUTH_FAILED:
        raise ProvisioningError("root key login was not rejected after SSH hardening")
    auth_methods = _probe_auth(settings, known_hosts_file, auth_probe)
    if not auth_methods.password_methods_disabled:
        raise ProvisioningError("password or keyboard-interactive SSH remains available")
    return BootstrapOutcome.APPLIED
