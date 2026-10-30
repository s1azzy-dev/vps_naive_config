from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    ("value", "returncode"),
    [
        ("https://github.com/owner/repo.git\n", 0),
        (" https://github.com/owner/repo.git\n", 1),
        ("https://github.com/owner/repo.git\n\n", 1),
        ("https://private-token@github.com/owner/repo.git\n", 1),
    ],
)
def test_role_repository_validator_checks_the_exact_stdin_value(
    value: str, returncode: int
) -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "src/naive_gateway_controller/repository.py")],
        input=value,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == returncode
    assert "private-token" not in result.stdout + result.stderr


def test_reproducible_version_pins() -> None:
    versions = dict(
        line.split("=", maxsplit=1)
        for line in (ROOT / "versions.env").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )
    assert re.fullmatch(r"[0-9a-f]{40}", versions["FORWARDPROXY_COMMIT"])
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", versions["CADDY_VERSION"])
    production = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in ("Dockerfile", "compose.yml", "versions.env")
    )
    assert re.search(r"(^|[^A-Za-z])latest([^A-Za-z]|$)", production, re.I) is None


def test_static_site_avoids_proxy_disclosure_and_external_resources() -> None:
    html = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "site").rglob("*.html"))
    assert html.strip()
    assert re.search(r"vpn|proxy|censorship|naiveproxy", html, re.I) is None
    assert re.search(r"https?://[^<{]", html, re.I) is None


def _ansible_secret_violations(directory: Path) -> list[str]:
    violations: list[str] = []
    secret_names = {
        "NAIVE_PASSWORD",
        "ansible_become_password",
        "ansible_password",
        "become_pass",
        "naive_password",
        "naive_gateway_password",
        "bootstrap_become_password",
        "managed_become_password",
        "user_password",
        "user_password_hash",
    }
    for path in (*directory.rglob("*.yml"), *directory.rglob("*.yaml")):
        content = path.read_text(encoding="utf-8")
        if re.search(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", content):
            violations.append(str(path))
        if re.search(r"https?://[^/@\s]+:[^/@\s]+@", content):
            violations.append(str(path))
        try:
            documents = list(yaml.safe_load_all(content))
        except yaml.YAMLError:
            continue
        stack = list(documents)
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                for key, child in value.items():
                    if (
                        key in secret_names
                        and isinstance(child, str)
                        and child
                        and not child.startswith("{{")
                        and not child.startswith("!vault")
                    ):
                        violations.append(f"{path}:{key}")
                    stack.append(child)
            elif isinstance(value, list):
                stack.extend(value)
    return violations


def test_secret_and_logging_policy(tmp_path: Path) -> None:
    tracked_env = subprocess.run(
        ["git", "ls-files", ".env"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert tracked_env.stdout == ""
    assert ".env" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert _ansible_secret_violations(ROOT / "provisioning") == []
    fixture = tmp_path / "leak.yml"
    fixture.write_text("ansible_become_password: plaintext-test-value\n", encoding="utf-8")
    assert _ansible_secret_violations(tmp_path)
    caddyfile = (ROOT / "Caddyfile").read_text(encoding="utf-8")
    assert "exclude http.log.error" in caddyfile
    assert len(re.findall(r"^\s*log\s*\{", caddyfile, re.MULTILINE)) == 1
    assert "mime text/plain text/xml application/xml" in caddyfile


def test_docker_publication_boundary_is_explicit() -> None:
    compose = yaml.safe_load((ROOT / "compose.yml").read_text(encoding="utf-8"))
    service = compose["services"]["caddy"]
    assert service["ports"] == [
        "0.0.0.0:80:80/tcp",
        "0.0.0.0:443:443/tcp",
    ]
    assert "network_mode" not in service
    assert all("/var/run/docker.sock" not in volume for volume in service["volumes"])
    assert all("/run/docker.sock" not in volume for volume in service["volumes"])

    for network in compose.get("networks", {}).values():
        assert network.get("driver", "bridge") not in {"host", "macvlan", "ipvlan"}


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker is not installed")
def test_docker_compose_config(tmp_path: Path) -> None:
    runtime_env = tmp_path / "gateway.env"
    runtime_env.write_text(
        "\n".join(
            (
                "DOMAIN=ci.example",
                "ACME_EMAIL=ci@example.com",
                "NAIVE_USER=0011223344556677",
                "NAIVE_PASSWORD=00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff",
            ),
        )
        + "\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            "versions.env",
            "--env-file",
            str(runtime_env),
            "-f",
            "compose.yml",
            "config",
            "--quiet",
        ],
        cwd=ROOT,
        check=True,
        env=environment,
    )
