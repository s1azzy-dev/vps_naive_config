from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

import naive_gateway_controller.cli as cli_module
from naive_gateway_controller.cli import main
from naive_gateway_controller.config import GatewaySettings
from naive_gateway_controller.network import NetworkReport
from naive_gateway_controller.preflight import PreflightMode, PreflightReport

ROOT = Path(__file__).resolve().parent.parent


def run_make(config: Path, target: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "make",
            "--no-print-directory",
            "-s",
            f"CONFIG_FILE={config}",
            target,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_check_config_cli_reads_only_selected_file(
    config_factory: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = config_factory()
    assert main(["check-config", "--config", str(config)]) == 0
    captured = capsys.readouterr()
    assert captured.out == "Configuration: OK\n"
    assert captured.err == ""


def test_cli_does_not_echo_invalid_password(
    config_factory: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "not allowed password"
    config = config_factory(NAIVE_USER="user", NAIVE_PASSWORD=secret)
    assert main(["check-config", "--config", str(config)]) == 1
    captured = capsys.readouterr()
    assert secret not in captured.err


def test_preflight_cli_renders_typed_report_without_network(
    config_factory: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_preflight(settings: GatewaySettings, known_hosts: Path) -> PreflightReport:
        assert settings.vps_user == "slazzy"
        assert known_hosts.name == "known_hosts"
        return PreflightReport(
            network=NetworkReport(
                vps_ipv4=("203.0.113.10",),
                vps_ipv6=(),
                domain_ipv4=("203.0.113.10",),
                domain_ipv6=(),
                ssh_target_reachable=True,
                unreachable_domain_ipv6=(),
            ),
            mode=PreflightMode.MANAGED,
            known_host_added=False,
        )

    monkeypatch.setattr(cli_module, "run_preflight", fake_preflight)
    config = config_factory()

    assert main(["preflight", "--config", str(config)]) == 0

    captured = capsys.readouterr()
    assert "Configuration: OK" in captured.out
    assert "Preflight mode: managed host ready" in captured.out
    assert captured.out.endswith("Preflight: PASS\n")


def test_make_check_config_passes_only_the_config_path(
    config_factory: Callable[..., Path],
) -> None:
    config = config_factory()
    completed = run_make(config, "check-config")
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.endswith("Configuration: OK\n")


def test_make_help_does_not_require_config(tmp_path: Path) -> None:
    completed = run_make(tmp_path / "missing.env", "help")
    assert completed.returncode == 0
    assert "make init" in completed.stdout


def test_make_init_is_private_and_never_overwrites(tmp_path: Path) -> None:
    config = tmp_path / "controller.env"
    created = run_make(config, "init")
    assert created.returncode == 0, created.stderr
    assert config.stat().st_mode & 0o777 == 0o600
    config.write_text(config.read_text(encoding="utf-8") + "# preserve-me\n", encoding="utf-8")

    repeated = run_make(config, "init")

    assert repeated.returncode == 0, repeated.stderr
    assert config.read_text(encoding="utf-8").endswith("# preserve-me\n")
