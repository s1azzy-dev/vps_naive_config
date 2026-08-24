"""Reproducible controller dependency and Ansible collection management."""

from __future__ import annotations

import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import cast

import yaml

from naive_gateway_controller.errors import ToolingError

EXPECTED_VERSIONS = {
    "ansible-core": "2.21.2",
    "ansible-lint": "26.6.0",
    "molecule": "26.6.0",
    "molecule-plugins": "26.7.15",
    "passlib": "1.7.4",
    "pytest-testinfra": "10.2.2",
    "uv": "0.12.5",
}


def project_root() -> Path:
    """Return the repository root for an editable or wheel installation."""
    return Path(__file__).resolve().parents[2]


def ansible_environment(root: Path) -> dict[str, str]:
    """Build a project-local Ansible environment."""
    environment = os.environ.copy()
    environment.update(
        {
            "ANSIBLE_CONFIG": str(root / "provisioning/ansible.cfg"),
            "ANSIBLE_HOME": str(root / ".ansible"),
            "ANSIBLE_LOCAL_TEMP": str(root / ".ansible/tmp"),
        },
    )
    return environment


def _load_collection_requirements(root: Path) -> list[dict[str, object]]:
    requirements_path = root / "provisioning/requirements.yml"
    try:
        raw = yaml.safe_load(requirements_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ToolingError("invalid provisioning/requirements.yml") from error
    if not isinstance(raw, dict) or not isinstance(raw.get("collections"), list):
        raise ToolingError("provisioning/requirements.yml must define a collections list")
    collections: list[dict[str, object]] = []
    for item in cast("list[object]", raw["collections"]):
        if not isinstance(item, dict):
            raise ToolingError("each Ansible collection requirement must be a mapping")
        collections.append(cast("dict[str, object]", item))
    return collections


def install_collections(root: Path | None = None) -> None:
    """Install only declared Ansible collections into the project-local path."""
    root = root or project_root()
    collections = _load_collection_requirements(root)
    (root / ".ansible/collections").mkdir(parents=True, exist_ok=True)
    (root / ".ansible/tmp").mkdir(parents=True, exist_ok=True)
    if not collections:
        print("No Ansible collections are required in the current phase.")
        return
    command = [
        str(Path(sys.prefix) / "bin/ansible-galaxy"),
        "collection",
        "install",
        "--requirements-file",
        str(root / "provisioning/requirements.yml"),
        "--collections-path",
        str(root / ".ansible/collections"),
    ]
    completed = subprocess.run(command, check=False, env=ansible_environment(root))
    if completed.returncode != 0:
        raise ToolingError("Ansible collection installation failed")


def _check_collection_versions(root: Path) -> None:
    requirements = _load_collection_requirements(root)
    if not requirements:
        return
    command = [
        str(Path(sys.prefix) / "bin/ansible-galaxy"),
        "collection",
        "list",
        "--format",
        "json",
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        env=ansible_environment(root),
        text=True,
    )
    if completed.returncode != 0:
        raise ToolingError("cannot inspect installed Ansible collections")
    try:
        locations = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ToolingError("ansible-galaxy returned invalid collection metadata") from error
    installed: dict[str, str] = {}
    if isinstance(locations, dict):
        for location in locations.values():
            if isinstance(location, dict):
                for name, metadata in location.items():
                    if isinstance(name, str) and isinstance(metadata, dict):
                        version = metadata.get("version")
                        if isinstance(version, str):
                            installed[name] = version
    for requirement in requirements:
        name = requirement.get("name")
        version = requirement.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise ToolingError("Ansible collections must have exact name and version values")
        if installed.get(name) != version:
            raise ToolingError(f"Ansible collection {name} does not match exact pin {version}")


def check_tooling(root: Path | None = None) -> None:
    """Verify system commands, locked Python tools, OpenSSH, and collections."""
    root = root or project_root()
    if sys.version_info[:2] not in {(3, 12), (3, 13), (3, 14)}:
        version = f"{sys.version_info.major}.{sys.version_info.minor}"
        raise ToolingError(f"Python 3.12-3.14 is required; found {version}")
    for command_name in ("ssh", "ssh-keygen", "make", "git"):
        if shutil.which(command_name) is None:
            raise ToolingError(f"required command is missing: {command_name}")
    openssh = subprocess.run(
        ["ssh", "-G", "-o", "StrictHostKeyChecking=accept-new", "localhost"],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if openssh.returncode != 0:
        raise ToolingError("OpenSSH client does not support StrictHostKeyChecking=accept-new")
    for distribution, expected in EXPECTED_VERSIONS.items():
        try:
            actual = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError as error:
            raise ToolingError(
                f"run 'make tooling'; missing Python package: {distribution}"
            ) from error
        if actual != expected:
            raise ToolingError(
                f"installed {distribution} {actual} does not match exact pin {expected}"
            )
    uv_binary = Path(sys.prefix) / "bin/uv"
    uv_environment = os.environ.copy()
    uv_environment["UV_CACHE_DIR"] = str(root / ".ansible/uv-cache")
    lock_check = subprocess.run(
        [str(uv_binary), "lock", "--check", "--offline"],
        check=False,
        cwd=root,
        env=uv_environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if lock_check.returncode != 0:
        raise ToolingError("uv.lock is missing or out of sync with pyproject.toml")
    _check_collection_versions(root)
    print(
        "Tooling: OK "
        f"(uv {EXPECTED_VERSIONS['uv']}, ansible-core {EXPECTED_VERSIONS['ansible-core']}, "
        f"ansible-lint {EXPECTED_VERSIONS['ansible-lint']})",
    )
