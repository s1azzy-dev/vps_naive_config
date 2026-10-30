from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from naive_gateway_controller.tooling import ansible_environment

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    ("scenario", "accepted"),
    [
        ("without-checkout", True),
        ("advanced-branch", True),
        ("pinned-commit", True),
        ("wrong-requested-commit", False),
        ("wrong-marker", False),
        ("missing-marker", False),
        ("wrong-image", False),
        ("outside-release-root", False),
    ],
)
def test_real_release_verification_uses_installed_state(
    tmp_path: Path, scenario: str, accepted: bool
) -> None:
    """Execute production Ansible tasks locally; stub only Docker and unavailable Git."""
    commit = "a" * 40
    other = "b" * 40
    root = tmp_path / "gateway"
    release = root / "releases" / commit
    release.mkdir(parents=True)
    marker = release / ".release-complete"
    marker.write_text(f"{other if scenario == 'wrong-marker' else commit}\n")
    if scenario == "missing-marker":
        marker.unlink()
    if scenario == "outside-release-root":
        release = tmp_path / commit
        release.mkdir()
        (release / ".release-complete").write_text(f"{commit}\n")
    (root / "current").symlink_to(release, target_is_directory=True)
    if scenario == "advanced-branch":
        branch = root / "repository/.git/refs/heads/main"
        branch.parent.mkdir(parents=True)
        branch.write_text(f"{other}\n")

    binaries = tmp_path / "bin"
    binaries.mkdir()
    git_accessed = tmp_path / "git-accessed"
    git = binaries / "git"
    git.write_text(f"#!/bin/sh\ntouch '{git_accessed}'\nexit 99\n")
    git.chmod(0o755)
    docker = binaries / "docker"
    image_commit = other if scenario == "wrong-image" else commit
    docker.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        "  ps) printf 'fixture-container\\n' ;;\n"
        f"  inspect) printf 'naive-gateway-caddy:git-{image_commit}\\n' ;;\n"
        "  *) exit 99 ;;\n"
        "esac\n"
    )
    docker.chmod(0o755)
    variables = {
        "ansible_connection": "local",
        "ansible_become": False,
        "ansible_python_interpreter": sys.executable,
        "verify_release_root": str(root),
        "verify_user": "fixture_user",
        "verify_ssh_port": 22,
        "verify_ref": (
            other
            if scenario == "wrong-requested-commit"
            else commit
            if scenario == "pinned-commit"
            else "main"
        ),
    }
    environment = ansible_environment(ROOT)
    environment["PATH"] = f"{binaries}{os.pathsep}{environment['PATH']}"
    result = subprocess.run(
        [
            str(Path(sys.prefix) / "bin/ansible-playbook"),
            "--inventory",
            "naive_gateway,",
            str(ROOT / "provisioning/playbooks/verify.yml"),
            "--tags",
            "release",
            "--extra-vars",
            json.dumps(variables),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert (result.returncode == 0) == accepted, result.stdout + result.stderr
    if not accepted:
        expected_failure = {
            "wrong-requested-commit": "Installed release marker, current pointer or requested commit disagree",
            "wrong-marker": "Installed release marker, current pointer or requested commit disagree",
            "missing-marker": "File not found",
            "wrong-image": "Running gateway image does not match",
            "outside-release-root": "Current must point to a managed release directory",
        }
        assert expected_failure[scenario] in result.stdout + result.stderr
    assert not git_accessed.exists(), "Verify contacted source Git instead of installed state"
