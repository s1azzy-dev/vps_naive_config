from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from naive_gateway_controller.config import GatewaySettings, load_settings
from naive_gateway_controller.errors import PreflightError
from naive_gateway_controller.network import NetworkReport
from naive_gateway_controller.preflight import PreflightMode, run_preflight
from naive_gateway_controller.ssh import SSHProbeResult, SSHStatus


class SequencedSSHProbe:
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


def valid_network(_host: str, _domain: str, _port: int, _timeout: float) -> NetworkReport:
    return NetworkReport(
        vps_ipv4=("192.0.2.10",),
        vps_ipv6=(),
        domain_ipv4=("192.0.2.10",),
        domain_ipv6=(),
        ssh_target_reachable=True,
        unreachable_domain_ipv6=(),
    )


@pytest.fixture
def settings(config_factory: Callable[..., Path]) -> GatewaySettings:
    return load_settings(config_factory(VPS_HOST="vps.example"))


def test_managed_user_is_checked_without_bootstrap(
    settings: GatewaySettings, tmp_path: Path
) -> None:
    ssh_probe = SequencedSSHProbe(SSHProbeResult(SSHStatus.OK, known_host_added=True))

    report = run_preflight(
        settings,
        tmp_path / "known_hosts",
        network_probe=valid_network,
        ssh_probe=ssh_probe,
    )

    assert report.mode is PreflightMode.MANAGED
    assert report.known_host_added
    assert ssh_probe.users == ["slazzy"]


def test_bootstrap_fallback_occurs_only_after_auth_rejection(
    settings: GatewaySettings,
    tmp_path: Path,
) -> None:
    ssh_probe = SequencedSSHProbe(
        SSHProbeResult(SSHStatus.AUTH_FAILED),
        SSHProbeResult(SSHStatus.OK),
    )

    report = run_preflight(
        settings,
        tmp_path / "known_hosts",
        network_probe=valid_network,
        ssh_probe=ssh_probe,
    )

    assert report.mode is PreflightMode.BOOTSTRAP
    assert ssh_probe.users == ["slazzy", "root"]


@pytest.mark.parametrize(
    ("results", "expected"),
    [
        ((SSHProbeResult(SSHStatus.HOST_KEY_CHANGED),), "host key changed"),
        ((SSHProbeResult(SSHStatus.CONNECTION_FAILED),), "transport failed"),
        (
            (
                SSHProbeResult(SSHStatus.AUTH_FAILED),
                SSHProbeResult(SSHStatus.AUTH_FAILED),
            ),
            "rejected for both managed and bootstrap users",
        ),
    ],
)
def test_unsafe_ssh_states_are_blocked(
    settings: GatewaySettings,
    tmp_path: Path,
    results: tuple[SSHProbeResult, ...],
    expected: str,
) -> None:
    with pytest.raises(PreflightError, match=expected):
        run_preflight(
            settings,
            tmp_path / "known_hosts",
            network_probe=valid_network,
            ssh_probe=SequencedSSHProbe(*results),
        )
