from __future__ import annotations

import pytest

from naive_gateway_controller.errors import PreflightError
from naive_gateway_controller.network import NetworkReport, collect_report, validate_report


def test_matching_ipv4_and_reachable_ssh() -> None:
    records = {
        ("vps.example", "A"): ("192.0.2.10",),
        ("vps.example", "AAAA"): (),
        ("proxy.example", "A"): ("192.0.2.10",),
        ("proxy.example", "AAAA"): (),
    }
    report = collect_report(
        "vps.example",
        "proxy.example",
        22,
        1,
        resolver=lambda name, kind, _timeout: records[(name, kind)],
        connector=lambda address, _port, _timeout: address == "192.0.2.10",
    )

    validate_report(report)
    assert report.ssh_target_reachable
    assert report.domain_ipv4 == ("192.0.2.10",)


def test_ipv4_literal_does_not_require_vps_dns() -> None:
    records = {
        ("proxy.example", "A"): ("192.0.2.10",),
        ("proxy.example", "AAAA"): (),
    }
    report = collect_report(
        "192.0.2.10",
        "proxy.example",
        22,
        1,
        resolver=lambda name, kind, _timeout: records[(name, kind)],
        connector=lambda _address, _port, _timeout: True,
    )
    assert report.vps_ipv4 == ("192.0.2.10",)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"domain_ipv4": ()}, "at least one A record"),
        ({"domain_ipv4": ("198.51.100.20",)}, "A records do not match"),
        ({"domain_ipv6": ("2001:db8::20",)}, "AAAA records do not match"),
        (
            {
                "vps_ipv6": ("2001:db8::10",),
                "domain_ipv6": ("2001:db8::10",),
                "unreachable_domain_ipv6": ("2001:db8::10",),
            },
            "AAAA record that is unreachable",
        ),
        ({"ssh_target_reachable": False}, "SSH port is unreachable"),
    ],
)
def test_invalid_network_reports_are_blocked(changes: dict[str, object], expected: str) -> None:
    values: dict[str, object] = {
        "vps_ipv4": ("192.0.2.10",),
        "vps_ipv6": (),
        "domain_ipv4": ("192.0.2.10",),
        "domain_ipv6": (),
        "ssh_target_reachable": True,
        "unreachable_domain_ipv6": (),
    }
    values.update(changes)
    report = NetworkReport(**values)  # type: ignore[arg-type]
    with pytest.raises(PreflightError, match=expected):
        validate_report(report)
