from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest

from naive_gateway_controller.config import GatewaySettings, load_settings
from naive_gateway_controller.errors import ProvisioningError
from naive_gateway_controller.network import NetworkReport
from naive_gateway_controller.preflight import PreflightMode, PreflightReport
from naive_gateway_controller.provisioning import (
    BootstrapOutcome,
    execute_ansible,
    hash_sudo_password,
    prompt_sudo_password,
    run_bootstrap,
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
    assert executor.variables["ansible_become_password"] == password
    assert str(executor.variables["user_password_hash"]).startswith("$6$")
    assert password not in " ".join(executor.command)
    assert password not in executor.environment.values()
    assert key_probe.users == ["root", "slazzy", "root"]


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
