"""Safe OpenSSH probe with project-local host-key persistence."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class SSHStatus(StrEnum):
    """Stable outcomes understood by the preflight state machine."""

    OK = "ok"
    AUTH_FAILED = "auth_failed"
    HOST_KEY_CHANGED = "host_key_changed"
    CONNECTION_FAILED = "connection_failed"
    LOCAL_ERROR = "local_error"


@dataclass(frozen=True)
class SSHProbeResult:
    """Secret-free SSH probe result."""

    status: SSHStatus
    known_host_added: bool = False


class SSHRunner(Protocol):
    """Injectable subprocess boundary used by unit tests."""

    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        """Run OpenSSH and return captured text output."""


def run_ssh(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run a non-interactive OpenSSH command with stable English diagnostics."""
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    return subprocess.run(
        list(command),
        check=False,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def _fingerprint(path: Path) -> bytes | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).digest()


def _local_contract_is_valid(
    host: str,
    port: int,
    user: str,
    identity_file: Path,
    known_hosts_file: Path,
    ssh_binary: str,
) -> bool:
    if re.fullmatch(r"[A-Za-z0-9.:-]+", host) is None or not 1 <= port <= 65535:
        return False
    if re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user) is None:
        return False
    if not identity_file.is_file() or not os.access(identity_file, os.R_OK):
        return False
    if not known_hosts_file.is_absolute() or not known_hosts_file.parent.is_dir():
        return False
    if shutil.which(ssh_binary) is None:
        return False
    if known_hosts_file.exists():
        mode = stat.S_IMODE(known_hosts_file.stat().st_mode)
        if not known_hosts_file.is_file() or mode != 0o600:
            return False
    return True


def _classify_result(completed: subprocess.CompletedProcess[str]) -> SSHStatus:
    stderr = completed.stderr
    if completed.returncode == 0:
        return SSHStatus.OK
    if re.search(
        r"REMOTE HOST IDENTIFICATION HAS CHANGED|Host key verification failed", stderr, re.I
    ):
        return SSHStatus.HOST_KEY_CHANGED
    if re.search(
        r"Permission denied|incorrect passphrase|sign_and_send_pubkey|no mutual signature algorithm",
        stderr,
        re.I,
    ):
        return SSHStatus.AUTH_FAILED
    return SSHStatus.CONNECTION_FAILED


def probe_ssh(
    *,
    host: str,
    port: int,
    user: str,
    identity_file: Path,
    known_hosts_file: Path,
    ssh_binary: str = "ssh",
    runner: SSHRunner = run_ssh,
) -> SSHProbeResult:
    """Authenticate with a key while executing only the read-only command ``true``."""
    if not _local_contract_is_valid(
        host,
        port,
        user,
        identity_file,
        known_hosts_file,
        ssh_binary,
    ):
        return SSHProbeResult(SSHStatus.LOCAL_ERROR)
    before = _fingerprint(known_hosts_file)
    command = [
        ssh_binary,
        "-F",
        "/dev/null",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "PasswordAuthentication=no",
        "-o",
        "KbdInteractiveAuthentication=no",
        "-o",
        "PreferredAuthentications=publickey",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"UserKnownHostsFile={known_hosts_file}",
        "-o",
        "GlobalKnownHostsFile=/dev/null",
        "-o",
        "HashKnownHosts=yes",
        "-o",
        "UpdateHostKeys=no",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "ConnectionAttempts=1",
        "-o",
        "ControlMaster=no",
        "-o",
        "ControlPath=none",
        "-o",
        "LogLevel=ERROR",
        "-p",
        str(port),
        "-i",
        str(identity_file),
        f"{user}@{host}",
        "true",
    ]
    try:
        completed = runner(command)
        if known_hosts_file.exists():
            known_hosts_file.chmod(0o600)
        after = _fingerprint(known_hosts_file)
    except OSError:
        return SSHProbeResult(SSHStatus.LOCAL_ERROR)
    return SSHProbeResult(_classify_result(completed), before != after)
