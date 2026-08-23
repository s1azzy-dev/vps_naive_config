"""Typed read-only preflight state machine."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from naive_gateway_controller.config import GatewaySettings
from naive_gateway_controller.errors import PreflightError
from naive_gateway_controller.network import NetworkReport, probe_network
from naive_gateway_controller.ssh import SSHProbeResult, SSHStatus, probe_ssh

NetworkProbe = Callable[[str, str, int, float], NetworkReport]


class SSHProbe(Protocol):
    """Typed keyword-only SSH probe boundary."""

    def __call__(
        self,
        *,
        host: str,
        port: int,
        user: str,
        identity_file: Path,
        known_hosts_file: Path,
    ) -> SSHProbeResult:
        """Return one safe SSH outcome."""


class PreflightMode(StrEnum):
    """Safe provisioning path selected by preflight."""

    MANAGED = "managed host ready"
    BOOTSTRAP = "bootstrap required"


@dataclass(frozen=True)
class PreflightReport:
    """Successful preflight facts safe to display."""

    network: NetworkReport
    mode: PreflightMode
    known_host_added: bool


def _raise_managed_failure(status: SSHStatus) -> None:
    if status is SSHStatus.HOST_KEY_CHANGED:
        raise PreflightError(
            "VPS host key changed; inspect provisioning/known_hosts before continuing.",
        )
    if status is SSHStatus.LOCAL_ERROR:
        raise PreflightError("Controller SSH probe configuration is invalid.")
    raise PreflightError("Managed-user SSH transport failed before authentication.")


def _raise_bootstrap_failure(status: SSHStatus) -> None:
    if status is SSHStatus.HOST_KEY_CHANGED:
        raise PreflightError(
            "VPS host key changed; inspect provisioning/known_hosts before continuing.",
        )
    if status is SSHStatus.AUTH_FAILED:
        raise PreflightError("SSH key was rejected for both managed and bootstrap users.")
    if status is SSHStatus.LOCAL_ERROR:
        raise PreflightError("Controller SSH probe configuration is invalid.")
    raise PreflightError("Bootstrap-user SSH transport failed before authentication.")


def run_preflight(
    settings: GatewaySettings,
    known_hosts_file: Path,
    *,
    network_probe: NetworkProbe = probe_network,
    ssh_probe: SSHProbe = probe_ssh,
) -> PreflightReport:
    """Validate network state, then choose managed or bootstrap SSH access."""
    network = network_probe(settings.vps_host, settings.domain, settings.vps_port, 3.0)
    managed = ssh_probe(
        host=settings.vps_host,
        port=settings.vps_port,
        user=settings.vps_user,
        identity_file=settings.ssh_private_key,
        known_hosts_file=known_hosts_file,
    )
    if managed.status is SSHStatus.OK:
        return PreflightReport(network, PreflightMode.MANAGED, managed.known_host_added)
    if managed.status is not SSHStatus.AUTH_FAILED:
        _raise_managed_failure(managed.status)
    bootstrap = ssh_probe(
        host=settings.vps_host,
        port=settings.vps_port,
        user=settings.vps_bootstrap_user,
        identity_file=settings.ssh_private_key,
        known_hosts_file=known_hosts_file,
    )
    if bootstrap.status is not SSHStatus.OK:
        _raise_bootstrap_failure(bootstrap.status)
    return PreflightReport(
        network,
        PreflightMode.BOOTSTRAP,
        managed.known_host_added or bootstrap.known_host_added,
    )
