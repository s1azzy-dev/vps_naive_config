"""Command-line facade used by stable Make targets."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from naive_gateway_controller.config import load_settings
from naive_gateway_controller.errors import ControllerError
from naive_gateway_controller.preflight import run_preflight
from naive_gateway_controller.provisioning import BootstrapOutcome, run_bootstrap
from naive_gateway_controller.tooling import check_tooling, install_collections, project_root


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gateway-controller")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("check-config", "preflight", "bootstrap"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--config", type=Path, default=Path(".env"))
    subparsers.add_parser("tooling-check")
    subparsers.add_parser("install-collections")
    return parser


def _print_preflight(config_path: Path) -> None:
    settings = load_settings(config_path)
    print("Configuration: OK")
    report = run_preflight(settings, project_root() / "provisioning/known_hosts")
    network = report.network
    print(f"VPS addresses: {', '.join((*network.vps_ipv4, *network.vps_ipv6))}")
    print(f"DOMAIN A: {', '.join(network.domain_ipv4)}")
    print(f"DOMAIN AAAA: {', '.join(network.domain_ipv6) or 'none'}")
    print(f"SSH port {settings.vps_port}: reachable")
    print("DNS validation: PASS")
    print("SSH host-key policy: PASS")
    print(f"Preflight mode: {report.mode.value}")
    print("Preflight: PASS")


def _print_bootstrap(config_path: Path) -> None:
    settings = load_settings(config_path)
    print("Configuration: OK")
    outcome = run_bootstrap(settings)
    if outcome is BootstrapOutcome.SKIPPED:
        print("Bootstrap: SKIP (managed host already hardened)")
    else:
        print("Bootstrap: PASS")


def main(argv: Sequence[str] | None = None) -> int:
    """Run one controller command and render only safe expected failures."""
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "check-config":
            load_settings(arguments.config)
            print("Configuration: OK")
        elif arguments.command == "preflight":
            _print_preflight(arguments.config)
        elif arguments.command == "bootstrap":
            _print_bootstrap(arguments.config)
        elif arguments.command == "tooling-check":
            check_tooling()
        elif arguments.command == "install-collections":
            install_collections()
    except ControllerError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0
