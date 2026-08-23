from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


def test_reproducible_version_pins() -> None:
    versions = dict(
        line.split("=", maxsplit=1)
        for line in (ROOT / "versions.env").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )
    assert len(versions["FORWARDPROXY_COMMIT"]) == 40
    assert versions["CADDY_VERSION"] == "2.11.4"
    production = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in ("Dockerfile", "compose.yml", "versions.env")
    )
    assert re.search(r"(^|[^A-Za-z])latest([^A-Za-z]|$)", production, re.I) is None


def test_believable_same_origin_static_site() -> None:
    required = (
        "site/index.html",
        "site/about/index.html",
        "site/notes/index.html",
        "site/assets/site.css",
        "site/assets/site.js",
        "site/assets/logo.svg",
        "site/assets/hero.svg",
        "site/assets/favicon.svg",
    )
    assert all((ROOT / path).is_file() and (ROOT / path).stat().st_size > 0 for path in required)
    homepage = (ROOT / "site/index.html").read_text(encoding="utf-8")
    for expected in (
        '<meta name="description"',
        "/assets/site.css",
        "/assets/site.js",
        "/about/",
        "/notes/keeping-services-boring.html",
    ):
        assert expected in homepage
    html = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "site").rglob("*.html"))
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


def test_role_argument_specs_exist_and_are_valid() -> None:
    roles = (ROOT / "provisioning/roles").iterdir()
    for role in roles:
        if not role.is_dir():
            continue
        spec_path = role / "meta/argument_specs.yml"
        data = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        assert data == {
            "argument_specs": {
                "main": {
                    "short_description": f"Validate inputs for the {role.name} role",
                    "options": {},
                },
            },
        }


def test_replaced_controller_shell_files_are_absent() -> None:
    removed = (
        "scripts/bootstrap-tooling.sh",
        "scripts/check-ansible-secrets.sh",
        "scripts/check-config.sh",
        "scripts/check-tooling.sh",
        "scripts/preflight-network.py",
        "scripts/preflight-ssh.sh",
        "tests/ansible-quality.sh",
        "tests/check-config.sh",
        "tests/preflight-network.py",
        "tests/preflight.sh",
        "tests/run.sh",
        "provisioning/playbooks/preflight.yml",
        "provisioning/requirements-controller.in",
        "provisioning/requirements-controller.txt",
    )
    assert all(not (ROOT / path).exists() for path in removed)
    assert not any((ROOT / "tests/fixtures").rglob("*"))


def test_make_does_not_import_or_export_dotenv_values() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "-include $(CONFIG_FILE)" not in makefile
    assert "export VPS_" not in makefile
    assert '"$(CONTROLLER)" check-config --config "$(CONFIG_FILE)"' in makefile
    assert '"$(CONTROLLER)" preflight --config "$(CONFIG_FILE)"' in makefile


def test_ci_workflow_covers_every_quality_layer() -> None:
    workflow_path = ROOT / ".github/workflows/ci.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(workflow_text)
    assert isinstance(workflow, dict)
    triggers = workflow.get("on", workflow.get(True))
    assert set(triggers) == {"push", "pull_request", "workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] is True
    assert "secrets." not in workflow_text
    assert "make preflight" not in workflow_text

    jobs = workflow["jobs"]
    assert set(jobs) == {"quality", "tests", "runtime-smoke"}
    for job in jobs.values():
        assert job["runs-on"] == "ubuntu-24.04"
        assert int(job["timeout-minutes"]) <= 20
        for step in job["steps"]:
            action = step.get("uses")
            if action is not None:
                assert re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}", action)

    quality_steps = jobs["quality"]["steps"]
    quality_commands = "\n".join(step.get("run", "") for step in quality_steps)
    assert "shellcheck" in quality_commands
    assert "make tooling" in quality_commands
    assert "make lint" in quality_commands
    assert any(step.get("env", {}).get("REQUIRE_SHELLCHECK") == "1" for step in quality_steps)

    test_job = jobs["tests"]
    assert test_job["strategy"]["fail-fast"] is False
    assert test_job["strategy"]["matrix"]["python-version"] == ["3.12", "3.13", "3.14"]
    test_commands = "\n".join(step.get("run", "") for step in test_job["steps"])
    assert "make tooling" in test_commands
    assert "make test" in test_commands

    runtime_commands = "\n".join(step.get("run", "") for step in jobs["runtime-smoke"]["steps"])
    for expected in ("compose.yml build", "caddy validate", "caddy list-modules", "smoke-local.sh"):
        assert expected in runtime_commands

    assert workflow_text.count("persist-credentials: false") == 3
    assert workflow_text.count("cache-local-path: .ansible/uv-cache") == 2


def test_remaining_shell_syntax() -> None:
    shell_files = [
        ROOT / "install.sh",
        ROOT / "tests/smoke-local.sh",
        *(ROOT / "scripts").glob("*.sh"),
    ]
    subprocess.run(["bash", "-n", *(str(path) for path in shell_files)], check=True)
    if shutil.which("shellcheck") is not None:
        subprocess.run(["shellcheck", *(str(path) for path in shell_files)], check=True)


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
