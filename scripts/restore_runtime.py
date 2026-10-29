#!/usr/bin/env python3
"""Restore an application backup onto a prepared empty host without Git/builds."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

from runtime_state import RuntimeState, atomic_write, private_file

VOLUMES = ("caddy_data", "caddy_config")


def safe_members(bundle: tarfile.TarFile) -> list[tarfile.TarInfo]:
    """Reject traversal, duplicate names, links and special files before extraction."""
    members = bundle.getmembers()
    seen: set[str] = set()
    for member in members:
        path = PurePosixPath(member.name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or str(path) in seen
            or not (member.isfile() or member.isdir())
        ):
            raise ValueError("unsafe backup archive member")
        seen.add(str(path))
    return members


def extract_regular_payload(
    bundle: tarfile.TarFile, stage: Path, members: list[tarfile.TarInfo]
) -> None:
    """Stream an already validated regular-file payload, also on Python 3.11.2."""
    for member in members:
        destination = stage / member.name
        if member.isdir():
            destination.mkdir(parents=True, exist_ok=True, mode=0o700)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        source = bundle.extractfile(member)
        if source is None:
            raise ValueError("missing backup file payload")
        with source, destination.open("xb") as output:
            shutil.copyfileobj(source, output)
        destination.chmod(member.mode & 0o755)


def restore_backup(archive: Path, root: Path, config: Path, expected_domain: str) -> None:
    """Restore only to an empty managed runtime; preserve backup on every failure."""
    private_file(archive)
    root.mkdir(parents=True, exist_ok=True, mode=0o750)
    config.mkdir(parents=True, exist_ok=True, mode=0o750)
    state = RuntimeState(root, config)
    if (
        state.current.exists()
        or state.current.is_symlink()
        or state.env.exists()
        or state.recovery.exists()
    ):
        raise ValueError(
            "restore requires an empty runtime; recover or migrate the existing service first"
        )
    containers = subprocess.run(
        [
            "docker",
            "ps",
            "--all",
            "--quiet",
            "--filter",
            "label=com.docker.compose.project=naive-gateway",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    if containers.stdout.strip():
        raise ValueError("restore refuses to replace existing gateway containers")
    existing_volumes = subprocess.run(
        ["docker", "volume", "ls", "--format", "{{.Name}}"],
        check=True,
        capture_output=True,
        text=True,
    )
    if set(existing_volumes.stdout.splitlines()) & {f"naive-gateway_{v}" for v in VOLUMES}:
        raise ValueError("restore refuses to overwrite existing gateway volumes")
    with tempfile.TemporaryDirectory(prefix=".restore-", dir=config) as temporary:
        stage = Path(temporary)
        with tarfile.open(archive, "r:gz") as bundle:
            members = safe_members(bundle)
            allowed = {
                "manifest.json",
                "runtime.env",
                "image.tar",
                *(f"{v}.tar.gz" for v in VOLUMES),
            }
            if any(m.name not in allowed and not m.name.startswith("release/") for m in members):
                raise ValueError("backup contains unexpected payload")
            extract_regular_payload(bundle, stage, members)
        manifest = json.loads((stage / "manifest.json").read_text())
        entries = [line.split("=", 1) for line in (stage / "runtime.env").read_text().splitlines()]
        if any(len(entry) != 2 for entry in entries):
            raise ValueError("invalid backup runtime format")
        values = dict(entries)
        if len(entries) != 4 or set(values) != {
            "DOMAIN",
            "ACME_EMAIL",
            "NAIVE_USER",
            "NAIVE_PASSWORD",
        }:
            raise ValueError("invalid backup runtime schema")
        if (
            values["DOMAIN"] != expected_domain
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]+", expected_domain) is None
        ):
            raise ValueError("backup domain does not match the controller DNS preflight")
        if (
            any(
                re.fullmatch(r"[A-Za-z0-9._~-]+", values[key]) is None
                for key in ("NAIVE_USER", "NAIVE_PASSWORD")
            )
            or re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+", values["ACME_EMAIL"]) is None
        ):
            raise ValueError("backup runtime values are not shell-safe")
        commit = manifest.get("commit", "")
        image = manifest.get("image", "")
        if (
            manifest.get("format") != 1
            or re.fullmatch(r"[0-9a-f]{40}", commit) is None
            or image != f"naive-gateway-caddy:git-{commit}"
        ):
            raise ValueError("unsupported backup manifest")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", manifest.get("image_id", "")) is None:
            raise ValueError("invalid backup image identity")
        if (stage / "release/.release-complete").read_text().strip() != commit:
            raise ValueError("backup commit mismatch")
        for volume in VOLUMES:
            with tarfile.open(stage / f"{volume}.tar.gz", "r:gz") as bundle:
                safe_members(bundle)
        subprocess.run(
            ["docker", "image", "load", "--input", str(stage / "image.tar")],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        image_id = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", image],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if image_id != manifest["image_id"]:
            raise ValueError("loaded Docker image does not match the backup")
        release = root / "releases" / commit
        release.parent.mkdir(mode=0o750, exist_ok=True)
        if release.exists():
            raise ValueError(
                "restore release already exists; inspect previous recovery before retrying"
            )
        shutil.copytree(stage / "release", release)
        atomic_write(release / ".runtime-env-path", f"{state.env}\n".encode())
        atomic_write(config / "gateway.env.pending", (stage / "runtime.env").read_bytes())
        created_volumes: list[str] = []
        try:
            for volume in VOLUMES:
                name = f"naive-gateway_{volume}"
                subprocess.run(
                    [
                        "docker",
                        "volume",
                        "create",
                        "--label",
                        "com.docker.compose.project=naive-gateway",
                        "--label",
                        f"com.docker.compose.volume={volume}",
                        name,
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                created_volumes.append(name)
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
                        f"type=volume,src={name},dst=/volume",
                        "--mount",
                        f"type=bind,src={stage},dst=/backup,readonly",
                        image,
                        "-xzf",
                        f"/backup/{volume}.tar.gz",
                        "-C",
                        "/volume",
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            state.begin(release)
            atomic_write(state.env, (stage / "runtime.env").read_bytes())
            state.compose(
                release,
                state.env,
                [
                    "up",
                    "-d",
                    "--wait",
                    "--wait-timeout",
                    "180",
                    "--no-build",
                    "--pull",
                    "never",
                    "caddy",
                ],
            )
            subprocess.run(
                ["bash", str(release / "scripts/check-server.sh")],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            state.commit()
        except BaseException:
            state.recover()
            for name in created_volumes:
                subprocess.run(
                    ["docker", "volume", "rm", name],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            shutil.rmtree(release)
            raise


if __name__ == "__main__":
    try:
        if os.geteuid() != 0:
            raise ValueError("restore requires root")
        restore_backup(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4])
    except (OSError, ValueError, KeyError, tarfile.TarError, subprocess.SubprocessError):
        print(
            "Restore failed; backup was retained. Inspect runtime, volumes and deployment-recovery before retrying.",
            file=sys.stderr,
        )
        sys.exit(1)
    print("Restore: PASS; source Git and image registries were not used.")
