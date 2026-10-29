#!/usr/bin/env python3
"""Durable application deployment transactions; never installs host software."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def private_file(path: Path) -> None:
    """Require private regular files owned by the effective administrator."""
    info = path.lstat()
    if (
        path.is_symlink()
        or not path.is_file()
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o777 != 0o600
    ):
        raise ValueError("unsafe application state file")


def sync_directory(path: Path) -> None:
    """Persist directory entries before active state can advance."""
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write(path: Path, content: bytes) -> None:
    """Persist private state atomically, including across interruption."""
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(path)
        sync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


class RuntimeState:
    """Keep env, release pointer and container recoverable as one transaction."""

    def __init__(self, root: Path, config: Path) -> None:
        self.root = root.resolve()
        self.config = config.resolve()
        self.recovery = self.config / "deployment-recovery"
        self.env = self.config / "gateway.env"
        self.current = self.root / "current"

    def release(self, value: str) -> Path:
        """Only operate on immutable, completed releases below the managed root."""
        path = Path(value)
        if (
            path.parent != self.root / "releases"
            or re.fullmatch(r"[0-9a-f]{40}", path.name) is None
        ):
            raise ValueError("invalid release in recovery state")
        if path.is_symlink() or path.resolve() != path or not path.is_dir():
            raise ValueError("unsafe recovery release")
        if (path / ".release-complete").read_text().strip() != path.name:
            raise ValueError("incomplete recovery release")
        return path

    def compose(self, release: Path, env: Path, arguments: list[str]) -> None:
        """Run Compose using the exact saved image, mounts and runtime env."""
        environment = os.environ.copy()
        for key in (
            "DOMAIN",
            "ACME_EMAIL",
            "NAIVE_USER",
            "NAIVE_PASSWORD",
            "CADDY_VERSION",
            "FORWARDPROXY_COMMIT",
        ):
            environment.pop(key, None)
        subprocess.run(
            [
                "docker",
                "compose",
                "--project-name",
                "naive-gateway",
                "--project-directory",
                str(release),
                "--env-file",
                str(release / "versions.env"),
                "--env-file",
                str(env),
                "-f",
                str(release / "compose.yml"),
                "-f",
                str(release / "deployment.yml"),
                *arguments,
            ],
            env=environment,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def point_current(self, release: Path) -> None:
        """Switch the operational pointer only after the chosen service is healthy."""
        temporary = self.root / ".current.pending"
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(release, target_is_directory=True)
        temporary.replace(self.current)
        sync_directory(self.root)

    def begin(self, candidate: Path) -> None:
        """Snapshot the accepted state before replacing any active bytes."""
        if self.recovery.exists():
            raise ValueError("unfinished deployment must be recovered first")
        candidate = self.release(str(candidate))
        previous = None
        if self.current.is_symlink():
            previous = str(self.release(str(self.current.resolve(strict=True))))
        elif self.current.exists():
            raise ValueError("current must be a managed release symlink")
        if bool(previous) != self.env.exists():
            raise ValueError("env/current are inconsistent; explicit recovery is required")
        pending = self.config / "gateway.env.pending"
        private_file(pending)
        stage = Path(tempfile.mkdtemp(prefix=".deployment-snapshot.", dir=self.config))
        try:
            atomic_write(stage / "candidate.env", pending.read_bytes())
            if previous:
                private_file(self.env)
                atomic_write(stage / "previous.env", self.env.read_bytes())
            atomic_write(
                stage / "state.json",
                json.dumps({"previous": previous, "candidate": str(candidate)}).encode(),
            )
            stage.replace(self.recovery)
            sync_directory(self.config)
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    def state(self) -> dict[str, str | None]:
        """Validate the durable snapshot before using any path or saved secret."""
        if self.recovery.is_symlink() or self.recovery.stat().st_mode & 0o777 != 0o700:
            raise ValueError("unsafe recovery directory")
        private_file(self.recovery / "state.json")
        state = json.loads((self.recovery / "state.json").read_text())
        if (
            not isinstance(state, dict)
            or set(state) != {"previous", "candidate"}
            or not isinstance(state["candidate"], str)
            or not (state["previous"] is None or isinstance(state["previous"], str))
        ):
            raise ValueError("invalid recovery metadata")
        self.release(state["candidate"])
        if state["previous"] is not None:
            self.release(state["previous"])
            private_file(self.recovery / "previous.env")
        private_file(self.recovery / "candidate.env")
        return state

    def recover(self) -> None:
        """Restore the accepted service, or stop an unaccepted first deployment."""
        if not self.recovery.exists():
            return
        state = self.state()
        if state["previous"]:
            previous = self.release(state["previous"])
            atomic_write(self.env, (self.recovery / "previous.env").read_bytes())
            self.compose(
                previous,
                self.env,
                [
                    "up",
                    "-d",
                    "--force-recreate",
                    "--wait",
                    "--wait-timeout",
                    "180",
                    "--no-build",
                    "--pull",
                    "never",
                    "caddy",
                ],
            )
            self.point_current(previous)
        else:
            candidate = self.release(str(state["candidate"]))
            self.compose(candidate, self.recovery / "candidate.env", ["down", "--remove-orphans"])
            self.env.unlink(missing_ok=True)
            self.current.unlink(missing_ok=True)
        shutil.rmtree(self.recovery)

    def commit(self) -> None:
        """Promote an accepted candidate and retain the previous successful state."""
        state = self.state()
        candidate = self.release(str(state["candidate"]))
        private_file(self.env)
        if self.env.read_bytes() != (self.recovery / "candidate.env").read_bytes():
            raise ValueError("active env differs from the accepted candidate")
        self.point_current(candidate)
        previous = self.config / "previous-deployment"
        if previous.exists():
            history = self.config / "deployment-history"
            history.mkdir(mode=0o700, exist_ok=True)
            archived = Path(tempfile.mkdtemp(prefix="previous-", dir=history))
            archived.rmdir()
            previous.replace(archived)
        self.recovery.replace(previous)


if __name__ == "__main__":
    try:
        if os.geteuid() != 0:
            raise ValueError("runtime recovery requires root")
        runtime = RuntimeState(Path(sys.argv[2]), Path(sys.argv[3]))
        operation = sys.argv[1]
        if operation == "begin":
            runtime.begin(Path(sys.argv[4]))
        elif operation == "recover":
            runtime.recover()
        elif operation == "commit":
            runtime.commit()
        else:
            raise ValueError("unknown runtime operation")
    except (OSError, ValueError, subprocess.SubprocessError):
        print(
            "Runtime transaction failed; preserve deployment-recovery and inspect the service before retrying.",
            file=sys.stderr,
        )
        sys.exit(1)
