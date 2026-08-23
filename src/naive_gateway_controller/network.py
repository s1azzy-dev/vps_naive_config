"""Typed DNS resolution and read-only TCP reachability checks."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass

import dns.exception
import dns.resolver

from naive_gateway_controller.errors import PreflightError

Resolver = Callable[[str, str, float], tuple[str, ...]]
Connector = Callable[[str, int, float], bool]


@dataclass(frozen=True)
class NetworkReport:
    """Resolved addresses and reachability results used by preflight."""

    vps_ipv4: tuple[str, ...]
    vps_ipv6: tuple[str, ...]
    domain_ipv4: tuple[str, ...]
    domain_ipv6: tuple[str, ...]
    ssh_target_reachable: bool
    unreachable_domain_ipv6: tuple[str, ...]


def resolve_records(name: str, record_type: str, timeout: float) -> tuple[str, ...]:
    """Resolve normalized IP records with a bounded lifetime."""
    resolver = dns.resolver.Resolver()
    try:
        answer = resolver.resolve(name, record_type, lifetime=timeout, raise_on_no_answer=False)
    except dns.resolver.NXDOMAIN as error:
        raise PreflightError(f"DNS name does not exist: {name}") from error
    except dns.exception.DNSException as error:
        raise PreflightError(
            f"DNS {record_type} lookup failed for {name}: {type(error).__name__}",
        ) from error
    if answer.rrset is None:
        return ()
    addresses = {str(ipaddress.ip_address(item.to_text())) for item in answer}
    return tuple(sorted(addresses, key=ipaddress.ip_address))


def address_reachable(address: str, port: int, timeout: float) -> bool:
    """Return whether a TCP connection can be established to one IP address."""
    parsed = ipaddress.ip_address(address)
    family = socket.AF_INET6 if parsed.version == 6 else socket.AF_INET
    target: tuple[str, int] | tuple[str, int, int, int]
    target = (address, port, 0, 0) if family == socket.AF_INET6 else (address, port)
    try:
        with socket.socket(family, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout)
            connection.connect(target)
    except OSError:
        return False
    return True


def host_addresses(
    host: str, timeout: float, resolver: Resolver
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Resolve a hostname or split an IP literal by address family."""
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        return resolver(host, "A", timeout), resolver(host, "AAAA", timeout)
    if literal.version == 4:
        return (str(literal),), ()
    return (), (str(literal),)


def collect_report(
    vps_host: str,
    domain: str,
    port: int,
    timeout: float,
    resolver: Resolver = resolve_records,
    connector: Connector = address_reachable,
) -> NetworkReport:
    """Collect DNS and TCP facts without making remote changes."""
    vps_ipv4, vps_ipv6 = host_addresses(vps_host, timeout, resolver)
    if not vps_ipv4 and not vps_ipv6:
        raise PreflightError(f"VPS_HOST has no A or AAAA records: {vps_host}")
    domain_ipv4 = resolver(domain, "A", timeout)
    domain_ipv6 = resolver(domain, "AAAA", timeout)
    reachable_vps = tuple(
        address for address in (*vps_ipv4, *vps_ipv6) if connector(address, port, timeout)
    )
    unreachable_domain_ipv6 = tuple(
        address for address in domain_ipv6 if not connector(address, port, timeout)
    )
    return NetworkReport(
        vps_ipv4=vps_ipv4,
        vps_ipv6=vps_ipv6,
        domain_ipv4=domain_ipv4,
        domain_ipv6=domain_ipv6,
        ssh_target_reachable=bool(reachable_vps),
        unreachable_domain_ipv6=unreachable_domain_ipv6,
    )


def validate_report(report: NetworkReport) -> None:
    """Enforce the deployment-blocking DNS and TCP invariants."""
    if not report.domain_ipv4:
        raise PreflightError("DOMAIN must have at least one A record.")
    if set(report.domain_ipv4) - set(report.vps_ipv4):
        raise PreflightError("DOMAIN A records do not match VPS_HOST addresses.")
    if set(report.domain_ipv6) - set(report.vps_ipv6):
        raise PreflightError("DOMAIN AAAA records do not match VPS_HOST addresses.")
    if report.unreachable_domain_ipv6:
        raise PreflightError("DOMAIN has an AAAA record that is unreachable on the SSH port.")
    if not report.ssh_target_reachable:
        raise PreflightError("VPS SSH port is unreachable from the controller.")


def probe_network(vps_host: str, domain: str, port: int, timeout: float = 3.0) -> NetworkReport:
    """Collect and validate a production network report."""
    report = collect_report(vps_host, domain, port, timeout)
    validate_report(report)
    return report
