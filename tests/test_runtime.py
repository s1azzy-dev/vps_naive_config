from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_common_uses_managed_env_and_clears_compose_environment(tmp_path: Path) -> None:
    release = tmp_path / "release"
    scripts = release / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(ROOT / "scripts/common.sh", scripts / "common.sh")
    shutil.copy2(ROOT / "versions.env", release / "versions.env")
    runtime = tmp_path / "gateway.env"
    runtime.write_text(
        "DOMAIN=managed.example\nACME_EMAIL=admin@example.com\n"
        "NAIVE_USER=saved-user\nNAIVE_PASSWORD=saved-password\n",
    )
    (release / ".runtime-env-path").write_text(f"{runtime}\n")
    (release / "deployment.yml").write_text("services: {}\n")
    current = tmp_path / "current"
    current.symlink_to(release, target_is_directory=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/bin/bash\n[[ -z ${NAIVE_PASSWORD+x} && -z ${DOMAIN+x} ]] || exit 8\n"
        'printf "%s\\n" "$@"\n',
    )
    docker.chmod(0o755)
    completed = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; load_project_env; compose config --quiet',
            "test",
            str(current / "scripts/common.sh"),
        ],
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "NAIVE_PASSWORD": "stale",
            "DOMAIN": "wrong.example",
        },
        check=True,
        capture_output=True,
        text=True,
    )
    assert str(runtime) in completed.stdout.splitlines()
    assert str(release / "deployment.yml") in completed.stdout.splitlines()
    assert "saved-password" not in completed.stdout
    assert str(release / ".env") not in completed.stdout
