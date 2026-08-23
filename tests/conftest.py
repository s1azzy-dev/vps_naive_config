from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture
def private_key(tmp_path: Path) -> Path:
    path = tmp_path / "id_ed25519"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(path)],
        check=True,
    )
    return path


@pytest.fixture
def config_factory(tmp_path: Path, private_key: Path) -> Callable[..., Path]:
    counter = 0

    def create(**overrides: str) -> Path:
        nonlocal counter
        counter += 1
        values = {
            "VPS_HOST": "203.0.113.10",
            "VPS_PORT": "22",
            "VPS_BOOTSTRAP_USER": "root",
            "VPS_USER": "slazzy",
            "SSH_PRIVATE_KEY": str(private_key),
            "SSH_PUBLIC_KEY": str(private_key.with_suffix(".pub")),
            "DOMAIN": "proxy.example.com",
            "ACME_EMAIL": "admin@example.com",
            "GATEWAY_REPOSITORY": "https://github.com/s1azzy-dev/vps_naive_config.git",
            "GATEWAY_REF": "main",
            "NAIVE_USER": "",
            "NAIVE_PASSWORD": "",
        }
        values.update(overrides)
        path = tmp_path / f"controller-{counter}.env"
        path.write_text(
            "\n".join(f"{name}={value}" for name, value in values.items()) + "\n",
            encoding="utf-8",
        )
        path.chmod(0o600)
        return path

    return create
