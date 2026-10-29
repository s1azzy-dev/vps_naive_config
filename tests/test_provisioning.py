from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest

from naive_gateway_controller import provisioning as provisioning_module
from naive_gateway_controller.cli import main
from naive_gateway_controller.config import GatewaySettings, load_settings
from naive_gateway_controller.errors import ProvisioningError
from naive_gateway_controller.network import NetworkReport
from naive_gateway_controller.preflight import PreflightMode, PreflightReport
from naive_gateway_controller.provisioning import (
    BootstrapOutcome,
    execute_ansible,
    hash_sudo_password,
    prompt_sudo_password,
    read_credentials,
    run_bootstrap,
    run_deploy,
    run_provision,
    run_verify,
)
from naive_gateway_controller.ssh import SSHAuthMethodsResult, SSHProbeResult, SSHStatus


class SequencedKeyProbe:
    def __init__(self, *results: SSHProbeResult) -> None:
        self.results = iter(results)
        self.users: list[str] = []

    def __call__(
        self,
        *,
        host: str,
        port: int,
        user: str,
        identity_file: Path,
        known_hosts_file: Path,
    ) -> SSHProbeResult:
        del host, port, identity_file, known_hosts_file
        self.users.append(user)
        return next(self.results)


class SequencedAuthProbe:
    def __init__(self, *results: SSHAuthMethodsResult) -> None:
        self.results = iter(results)

    def __call__(
        self,
        *,
        host: str,
        port: int,
        user: str,
        identity_file: Path,
        known_hosts_file: Path,
    ) -> SSHAuthMethodsResult:
        del host, port, user, identity_file, known_hosts_file
        return next(self.results)


class RecordingExecutor:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.command: Sequence[str] = ()
        self.variables: Mapping[str, object] = {}
        self.environment: Mapping[str, str] = {}

    def __call__(
        self,
        command: Sequence[str],
        variables: Mapping[str, object],
        environment: Mapping[str, str],
    ) -> int:
        self.command = command
        self.variables = variables
        self.environment = environment
        return self.returncode


def _network() -> NetworkReport:
    return NetworkReport(
        vps_ipv4=("192.0.2.10",),
        vps_ipv6=(),
        domain_ipv4=("192.0.2.10",),
        domain_ipv6=(),
        ssh_target_reachable=True,
        unreachable_domain_ipv6=(),
    )


def _preflight(mode: PreflightMode) -> Callable[[GatewaySettings, Path], PreflightReport]:
    def run(_settings: GatewaySettings, _known_hosts: Path) -> PreflightReport:
        return PreflightReport(_network(), mode, False)

    return run


@pytest.fixture
def settings(config_factory: Callable[..., Path]) -> GatewaySettings:
    return load_settings(config_factory(VPS_HOST="vps.example"))


def disabled_auth() -> SSHAuthMethodsResult:
    return SSHAuthMethodsResult(SSHStatus.AUTH_FAILED, ("publickey",), True)


def test_password_prompt_requires_matching_nonempty_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(("correct horse battery staple", "correct horse battery staple"))
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(responses))
    assert prompt_sudo_password() == "correct horse battery staple"

    mismatched = iter(("first", "second"))
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(mismatched))
    with pytest.raises(ProvisioningError, match="does not match"):
        prompt_sudo_password()


def test_password_hash_is_linux_sha512_crypt() -> None:
    password = "controller-only-test-password"
    password_hash = hash_sudo_password(password)
    assert password_hash.startswith("$6$rounds=656000$")
    assert password not in password_hash


def test_execute_ansible_uses_an_inherited_pipe_for_extra_vars(tmp_path: Path) -> None:
    output = tmp_path / "payload.json"
    fake_secret = "pipe-only-test-secret"
    script = (
        "import pathlib,sys; "
        "source=next(value[1:] for value in sys.argv if value.startswith('@/dev/fd/')); "
        "pathlib.Path(sys.argv[1]).write_text(pathlib.Path(source).read_text())"
    )
    command = [sys.executable, "-c", script, str(output)]

    assert execute_ansible(command, {"ansible_become_password": fake_secret}, {}) == 0
    assert fake_secret not in " ".join(command)
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "ansible_become_password": fake_secret,
    }


def test_new_host_bootstrap_applies_user_then_requires_safe_post_checks(
    settings: GatewaySettings,
    tmp_path: Path,
) -> None:
    password = "not-in-process-arguments"
    key_probe = SequencedKeyProbe(
        SSHProbeResult(SSHStatus.OK),
        SSHProbeResult(SSHStatus.OK),
        SSHProbeResult(SSHStatus.AUTH_FAILED),
    )
    executor = RecordingExecutor()

    outcome = run_bootstrap(
        settings,
        root=tmp_path,
        password_prompt=lambda: password,
        preflight_runner=_preflight(PreflightMode.BOOTSTRAP),
        ssh_probe=key_probe,
        auth_probe=SequencedAuthProbe(disabled_auth()),
        ansible_executor=executor,
    )

    assert outcome is BootstrapOutcome.APPLIED
    assert executor.variables["bootstrap_apply_user"] is True
    assert executor.variables["managed_become_password"] == password
    assert executor.variables["bootstrap_become_password"] == ""
    assert "ansible_become_password" not in executor.variables
    assert str(executor.variables["user_password_hash"]).startswith("$6$")
    assert password not in " ".join(executor.command)
    assert password not in executor.environment.values()
    assert key_probe.users == ["root", "slazzy", "root"]


@pytest.mark.parametrize("bootstrap_password", ["bootstrap-only-secret", ""])
def test_nonroot_bootstrap_separates_passwords_and_checks_literal_root(
    config_factory: Callable[..., Path],
    tmp_path: Path,
    bootstrap_password: str,
) -> None:
    settings = load_settings(config_factory(VPS_BOOTSTRAP_USER="ubuntu"))
    executor = RecordingExecutor()
    probe = SequencedKeyProbe(
        SSHProbeResult(SSHStatus.OK),
        SSHProbeResult(SSHStatus.OK),
        SSHProbeResult(SSHStatus.AUTH_FAILED),
    )
    run_bootstrap(
        settings,
        root=tmp_path,
        password_prompt=lambda: "managed-secret",
        bootstrap_password_prompt=lambda: bootstrap_password,
        preflight_runner=_preflight(PreflightMode.BOOTSTRAP),
        ssh_probe=probe,
        auth_probe=SequencedAuthProbe(disabled_auth()),
        ansible_executor=executor,
    )
    assert probe.users == ["ubuntu", "slazzy", "root"]
    assert executor.variables["bootstrap_become_password"] == bootstrap_password
    assert executor.variables["managed_become_password"] == "managed-secret"
    assert "ansible_become_password" not in executor.variables
    assert "managed-secret" not in " ".join(executor.command)
    assert not bootstrap_password or bootstrap_password not in " ".join(executor.command)


def test_managed_host_skips_root_bootstrap_but_applies_later_host_roles(
    settings: GatewaySettings,
    tmp_path: Path,
) -> None:
    executor = RecordingExecutor()
    key_probe = SequencedKeyProbe(
        SSHProbeResult(SSHStatus.AUTH_FAILED),
        SSHProbeResult(SSHStatus.OK),
        SSHProbeResult(SSHStatus.AUTH_FAILED),
    )

    outcome = run_bootstrap(
        settings,
        root=tmp_path,
        password_prompt=lambda: "existing-managed-password",
        preflight_runner=_preflight(PreflightMode.MANAGED),
        ssh_probe=key_probe,
        auth_probe=SequencedAuthProbe(disabled_auth()),
        ansible_executor=executor,
    )

    assert outcome is BootstrapOutcome.APPLIED
    assert executor.variables["bootstrap_apply_user"] is False
    assert executor.variables["firewall_ssh_port"] == settings.vps_port
    assert key_probe.users == ["root", "slazzy", "root"]


def test_post_hardening_root_access_is_a_blocking_failure(
    settings: GatewaySettings,
    tmp_path: Path,
) -> None:
    with pytest.raises(ProvisioningError, match="root key login was not rejected"):
        run_bootstrap(
            settings,
            root=tmp_path,
            password_prompt=lambda: "test-password",
            preflight_runner=_preflight(PreflightMode.BOOTSTRAP),
            ssh_probe=SequencedKeyProbe(
                SSHProbeResult(SSHStatus.OK),
                SSHProbeResult(SSHStatus.OK),
                SSHProbeResult(SSHStatus.OK),
            ),
            auth_probe=SequencedAuthProbe(disabled_auth()),
            ansible_executor=RecordingExecutor(),
        )


def test_deploy_refuses_bootstrap_before_prompt_or_execution(settings: GatewaySettings) -> None:
    executor = RecordingExecutor()

    def unexpected_prompt() -> str:
        pytest.fail("deploy must refuse an unmanaged host before asking for sudo")

    with pytest.raises(ProvisioningError, match="run make bootstrap first"):
        run_deploy(
            settings,
            password_prompt=unexpected_prompt,
            preflight_runner=_preflight(PreflightMode.BOOTSTRAP),
            ansible_executor=executor,
        )
    assert executor.command == ()


def test_deploy_uses_managed_user_and_pipe_only_secrets(
    config_factory: Callable[..., Path],
) -> None:
    password = "secret"
    settings = load_settings(config_factory(NAIVE_USER="explicit-user", NAIVE_PASSWORD=password))
    executor = RecordingExecutor()
    run_deploy(
        settings,
        password_prompt=lambda: "sudo-secret",
        preflight_runner=_preflight(PreflightMode.MANAGED),
        ansible_executor=executor,
    )
    assert executor.command[-1].endswith("/playbooks/deploy.yml")
    assert executor.variables["ansible_user"] == settings.vps_user
    assert executor.variables["naive_gateway_ref"] == settings.gateway_ref
    assert executor.variables["naive_gateway_password"] == "secret"
    assert executor.variables["ansible_become_password"] == "sudo-secret"
    assert "secret" not in " ".join(executor.command)
    assert "sudo-secret" not in executor.environment.values()
    assert "bootstrap_apply_user" not in executor.variables


def test_deploy_failure_is_reported_without_success(settings: GatewaySettings) -> None:
    with pytest.raises(ProvisioningError, match="rerun make deploy"):
        run_deploy(
            settings,
            password_prompt=lambda: "sudo-secret",
            preflight_runner=_preflight(PreflightMode.MANAGED),
            ansible_executor=RecordingExecutor(returncode=2),
        )


def test_provision_reuses_one_password_across_bootstrap_deploy_and_verify(
    settings: GatewaySettings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    phases: list[tuple[str, str]] = []
    password = "single-sudo-password"
    monkeypatch.setattr(
        provisioning_module, "check_playbook_syntax", lambda _root: phases.append(("syntax", ""))
    )
    monkeypatch.setattr(provisioning_module, "run_preflight", _preflight(PreflightMode.BOOTSTRAP))
    monkeypatch.setattr(provisioning_module, "prompt_sudo_password", lambda: password)

    def fake_stage(name: str) -> Callable[..., None]:
        def run(_settings: GatewaySettings, **kwargs: object) -> None:
            prompt = kwargs["password_prompt"]
            assert callable(prompt)
            phases.append((name, prompt()))

        return run

    monkeypatch.setattr(provisioning_module, "run_bootstrap", fake_stage("bootstrap"))
    monkeypatch.setattr(provisioning_module, "run_deploy", fake_stage("deploy"))
    monkeypatch.setattr(provisioning_module, "run_verify", fake_stage("verify"))

    assert run_provision(settings, root=tmp_path) == password
    assert phases == [
        ("syntax", ""),
        ("bootstrap", password),
        ("deploy", password),
        ("verify", password),
    ]


@pytest.mark.parametrize(
    "broken_path",
    [
        "playbooks/bootstrap.yml",
        "playbooks/deploy.yml",
        "playbooks/verify.yml",
        "playbooks/restore.yml",
        "roles/naive_gateway/tasks/credentials.yml",
    ],
)
def test_provision_with_invalid_playbook_stops_before_any_vps_interaction(
    broken_path: str,
    config_factory: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = Path(__file__).resolve().parent.parent
    root = tmp_path / "controller"
    shutil.copytree(
        source / "provisioning",
        root / "provisioning",
        ignore=shutil.ignore_patterns("molecule", "known_hosts", "__pycache__"),
    )
    (root / ".ansible").mkdir()
    (root / ".ansible/collections").symlink_to(source / ".ansible/collections")
    secret = "must-not-appear-in-parser-output"
    (root / "provisioning" / broken_path).write_text(
        f"---\n- name: {secret}\n  invalid: [\n", encoding="utf-8"
    )

    def unexpected_remote_work(*_args: object, **_kwargs: object) -> None:
        pytest.fail("invalid playbooks must stop provision before probes, prompts or VPS changes")

    monkeypatch.setattr(provisioning_module, "project_root", lambda: root)
    monkeypatch.setattr(provisioning_module, "run_preflight", unexpected_remote_work)
    monkeypatch.setattr(provisioning_module, "prompt_sudo_password", unexpected_remote_work)
    monkeypatch.setattr(provisioning_module, "prompt_current_sudo_password", unexpected_remote_work)
    monkeypatch.setattr(provisioning_module, "run_bootstrap", unexpected_remote_work)
    monkeypatch.setattr(provisioning_module, "run_deploy", unexpected_remote_work)
    monkeypatch.setattr(provisioning_module, "run_verify", unexpected_remote_work)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)

    assert main(["provision", "--config", str(config_factory())]) == 1

    output = capsys.readouterr()
    assert "local Ansible syntax check failed" in output.err
    assert "make ansible-check" in output.err
    assert "no VPS changes were made" in output.err
    assert secret not in output.out + output.err
    assert "PASS" not in output.out
    assert not (root / "provisioning/known_hosts").exists()


def test_verify_refuses_root_ssh_before_invoking_ansible(settings: GatewaySettings) -> None:
    executor = RecordingExecutor()
    with pytest.raises(ProvisioningError, match="root key login"):
        run_verify(
            settings,
            preflight_runner=_preflight(PreflightMode.MANAGED),
            ssh_probe=SequencedKeyProbe(SSHProbeResult(SSHStatus.OK)),
            auth_probe=SequencedAuthProbe(disabled_auth()),
            ansible_executor=executor,
        )
    assert executor.command == ()


def test_provision_reconciles_firewall_even_when_ssh_is_hardened(
    settings: GatewaySettings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    phases: list[str] = []
    monkeypatch.setattr(
        provisioning_module, "check_playbook_syntax", lambda _root: phases.append("syntax")
    )
    monkeypatch.setattr(provisioning_module, "run_preflight", _preflight(PreflightMode.MANAGED))
    monkeypatch.setattr(
        provisioning_module, "_probe_key", lambda *_args: SSHProbeResult(SSHStatus.AUTH_FAILED)
    )
    monkeypatch.setattr(provisioning_module, "_probe_auth", lambda *_args: disabled_auth())
    monkeypatch.setattr(provisioning_module, "prompt_current_sudo_password", lambda: "existing")

    def run_stage(name: str) -> Callable[..., None]:
        def run(_settings: GatewaySettings, **kwargs: object) -> None:
            prompt = kwargs["password_prompt"]
            assert callable(prompt)
            assert prompt() == "existing"
            phases.append(name)

        return run

    monkeypatch.setattr(provisioning_module, "run_bootstrap", run_stage("bootstrap"))
    monkeypatch.setattr(provisioning_module, "run_deploy", run_stage("deploy"))
    monkeypatch.setattr(provisioning_module, "run_verify", run_stage("verify"))

    assert run_provision(settings, root=tmp_path) == "existing"
    assert phases == ["syntax", "bootstrap", "deploy", "verify"]


def test_read_credentials_passes_sudo_password_only_via_stdin(
    settings: GatewaySettings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    password = "sudo-password"
    secret = "stored-proxy-password"
    calls: list[tuple[Sequence[str], Mapping[str, object]]] = []

    def fake_run(command: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=f"DOMAIN=proxy.example.com\nACME_EMAIL=admin@example.com\n"
            f"NAIVE_USER=stored-user\nNAIVE_PASSWORD={secret}\n",
            stderr="",
        )

    monkeypatch.setattr(provisioning_module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        provisioning_module,
        "run_preflight",
        lambda *_args: pytest.fail("credentials must not depend on gateway DNS"),
    )
    known_hosts = tmp_path / "provisioning/known_hosts"
    known_hosts.parent.mkdir()
    known_hosts.write_text("test host key\n")
    known_hosts.chmod(0o600)
    result = read_credentials(
        settings,
        None,
        root=tmp_path,
        password_prompt=lambda: password,
    )
    assert result == ("proxy.example.com", "stored-user", secret)
    command, kwargs = calls[0]
    assert kwargs["input"] == f"{password}\n"
    assert password not in " ".join(command)
    assert secret not in " ".join(command)
    assert "StrictHostKeyChecking=yes" in " ".join(command)


@pytest.mark.parametrize("returncode", [1, 255])
def test_credentials_refuse_sudo_and_host_key_failures_without_leaking_output(
    settings: GatewaySettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
) -> None:
    known_hosts = tmp_path / "provisioning/known_hosts"
    known_hosts.parent.mkdir()
    known_hosts.write_text("known key\n")
    known_hosts.chmod(0o600)
    monkeypatch.setattr(
        provisioning_module.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, returncode, stdout="sensitive-runtime", stderr="sensitive-error"
        ),
    )
    with pytest.raises(ProvisioningError, match="check SSH and sudo") as error:
        read_credentials(settings, "password", root=tmp_path)
    assert "sensitive" not in str(error.value)
