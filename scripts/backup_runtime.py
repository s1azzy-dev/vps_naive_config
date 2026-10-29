#!/usr/bin/env python3
"""Export a self-contained, private application backup without Git credentials."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from runtime_state import RuntimeState, atomic_write, private_file

VOLUMES = ("caddy_data", "caddy_config")
RUNTIME_FILES = (
    "Caddyfile",
    "Dockerfile",
    "Makefile",
    "compose.yml",
    "deployment.yml",
    "versions.env",
    "site",
    "scripts",
    ".release-complete",
    ".runtime-env-path",
)


def create_backup(release: Path, env: Path, destination: Path) -> Path:
    """Save runtime files, the exact image and both certificate/config volumes."""
    private_file(env)
    commit = (release / ".release-complete").read_text().strip()
    state = RuntimeState(release.parent.parent, env.parent)
    state.release(str(release))
    if state.recovery.exists():
        raise ValueError("recover the unfinished deployment before backup")
    image = f"naive-gateway-caddy:git-{commit}"
    image_id = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination.is_symlink() or destination.stat().st_uid != os.geteuid():
        raise ValueError("backup directory must be private")
    destination.chmod(0o700)
    with tempfile.TemporaryDirectory(prefix=".backup-", dir=destination) as temporary:
        stage = Path(temporary)
        atomic_write(stage / "runtime.env", env.read_bytes())
        atomic_write(
            stage / "manifest.json",
            json.dumps(
                {"format": 1, "commit": commit, "image": image, "image_id": image_id}
            ).encode(),
        )
        subprocess.run(
            ["docker", "image", "save", "--output", str(stage / "image.tar"), image], check=True
        )
        for volume in VOLUMES:
            subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--entrypoint",
                    "tar",
                    "--mount",
                    f"type=volume,src=naive-gateway_{volume},dst=/volume,readonly",
                    "--mount",
                    f"type=bind,src={stage},dst=/backup",
                    image,
                    "-czf",
                    f"/backup/{volume}.tar.gz",
                    "-C",
                    "/volume",
                    ".",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        fd, output = tempfile.mkstemp(
            prefix=f"naive-gateway-{commit[:12]}-", suffix=".tar.gz", dir=destination
        )
        os.close(fd)
        archive = Path(output)
        try:
            with tarfile.open(archive, "w:gz") as bundle:
                for name in RUNTIME_FILES:
                    path = release / name
                    for member in (path, *(path.rglob("*") if path.is_dir() else ())):
                        if member.is_symlink() or not (member.is_file() or member.is_dir()):
                            raise ValueError("backup source contains unsupported special files")
                    bundle.add(path, arcname=f"release/{name}")
                for name in (
                    "manifest.json",
                    "runtime.env",
                    "image.tar",
                    *(f"{volume}.tar.gz" for volume in VOLUMES),
                ):
                    bundle.add(stage / name, arcname=name)
            archive.chmod(0o600)
            return archive
        except BaseException:
            archive.unlink(missing_ok=True)
            raise


if __name__ == "__main__":
    try:
        if os.geteuid() != 0:
            raise ValueError("backup requires root")
        result = create_backup(
            Path(sys.argv[1]), Path(sys.argv[2]), Path("/var/backups/naive-gateway")
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        print("Backup failed; no complete archive was produced.", file=sys.stderr)
        sys.exit(1)
    print(
        f"Backup created: {result}\nWARNING: contains credentials, certificate keys and Docker image; store as a secret."
    )
