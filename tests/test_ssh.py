from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from naive_gateway_controller.ssh import (
    SSHProbeResult,
    SSHStatus,
    probe_ssh,
    probe_ssh_auth_methods,
)


class FakeRunner:
    def __init__(self, known_hosts: Path, returncode: int = 0, stderr: str = "") -> None:
        self.known_hosts = known_hosts
        self.returncode = returncode
        self.stderr = stderr
        self.command: Sequence[str] = ()

    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.command = command
        if not self.known_hosts.exists():
            self.known_hosts.write_text("fake-host ssh-ed25519 AAAATESTONLY\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, self.returncode, stdout="", stderr=self.stderr)


def run_probe(private_key: Path, known_hosts: Path, runner: FakeRunner) -> SSHProbeResult:
    return probe_ssh(
        host="vps.example",
        port=22,
        user="slazzy",
        identity_file=private_key,
        known_hosts_file=known_hosts,
        runner=runner,
    )


def test_success_uses_accept_new_and_only_remote_true(private_key: Path, tmp_path: Path) -> None:
    known_hosts = tmp_path / "known_hosts"
    runner = FakeRunner(known_hosts)

    result = run_probe(private_key, known_hosts, runner)

    assert result == SSHProbeResult(SSHStatus.OK, known_host_added=True)
    assert runner.command[-1] == "true"
    assert "StrictHostKeyChecking=accept-new" in runner.command
    assert "BatchMode=yes" in runner.command
    assert known_hosts.stat().st_mode & 0o777 == 0o600


def test_authentication_failure_is_classified(private_key: Path, tmp_path: Path) -> None:
    known_hosts = tmp_path / "known_hosts"
    result = run_probe(
        private_key,
        known_hosts,
        FakeRunner(known_hosts, 255, "Permission denied (publickey)."),
    )
    assert result.status is SSHStatus.AUTH_FAILED


def test_changed_host_key_is_classified(private_key: Path, tmp_path: Path) -> None:
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("existing\n", encoding="utf-8")
    known_hosts.chmod(0o600)
    result = run_probe(
        private_key,
        known_hosts,
        FakeRunner(known_hosts, 255, "REMOTE HOST IDENTIFICATION HAS CHANGED!"),
    )
    assert result.status is SSHStatus.HOST_KEY_CHANGED


def test_insecure_known_hosts_is_a_local_error(private_key: Path, tmp_path: Path) -> None:
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("existing\n", encoding="utf-8")
    known_hosts.chmod(0o644)
    result = run_probe(private_key, known_hosts, FakeRunner(known_hosts))
    assert result.status is SSHStatus.LOCAL_ERROR


def test_auth_method_probe_requires_observed_password_methods_to_be_absent(
    private_key: Path,
    tmp_path: Path,
) -> None:
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("existing\n", encoding="utf-8")
    known_hosts.chmod(0o600)
    runner = FakeRunner(
        known_hosts,
        255,
        "debug1: Authentications that can continue: publickey\nPermission denied (publickey).\n",
    )

    result = probe_ssh_auth_methods(
        host="vps.example",
        port=22,
        user="slazzy",
        identity_file=private_key,
        known_hosts_file=known_hosts,
        runner=runner,
    )

    assert result.password_methods_disabled
    assert result.offered_methods == ("publickey",)
    assert "PubkeyAuthentication=no" in runner.command
    assert "NumberOfPasswordPrompts=0" in runner.command


def test_auth_method_probe_rejects_a_server_offering_password(
    private_key: Path,
    tmp_path: Path,
) -> None:
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("existing\n", encoding="utf-8")
    known_hosts.chmod(0o600)
    result = probe_ssh_auth_methods(
        host="vps.example",
        port=22,
        user="slazzy",
        identity_file=private_key,
        known_hosts_file=known_hosts,
        runner=FakeRunner(
            known_hosts,
            255,
            "debug1: Authentications that can continue: publickey,password,keyboard-interactive\n"
            "Permission denied (publickey,password,keyboard-interactive).\n",
        ),
    )

    assert not result.password_methods_disabled
    assert "password" in result.offered_methods
