from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    ("scenario", "message"),
    [
        ("closed", "Server checks passed"),
        ("redirect", "Server checks passed"),
        ("fallback", "Server checks passed"),
        ("open", "unauthenticated CONNECT was accepted"),
        ("transport", "anonymous proxy check inconclusive"),
        ("tls-error", "anonymous proxy check inconclusive"),
        ("disclosure", "obvious forward-proxy response"),
        ("targets-down", "proxy checks inconclusive"),
    ],
)
def test_server_checks_require_real_anonymous_rejection(
    tmp_path: Path, scenario: str, message: str
) -> None:
    release = tmp_path / "release"
    shutil.copytree(ROOT / "scripts", release / "scripts")
    shutil.copy2(ROOT / "versions.env", release / "versions.env")
    runtime = tmp_path / "runtime.env"
    runtime.write_text(
        "DOMAIN=gateway.example\nACME_EMAIL=admin@example.com\n"
        "NAIVE_USER=private-user\nNAIVE_PASSWORD=private-password\n"
    )
    (release / ".runtime-env-path").write_text(f"{runtime}\n")
    (release / "deployment.yml").write_text("services: {}\n")
    binary = tmp_path / "bin"
    binary.mkdir()
    fake = binary / "tool"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\nfrom pathlib import Path\n"
        "name=Path(sys.argv[0]).name; args=sys.argv[1:]; mode=os.environ['SCENARIO']\n"
        "if name=='docker':\n"
        " print('healthy' if args[0]=='inspect' else 'container-id' if args[0]=='compose' else ''); sys.exit()\n"
        "if name=='openssl':\n"
        " print('Verify return code: 0 (ok)\\nALPN protocol: h2'); sys.exit()\n"
        "if '--help' in args: print('--proxy-http2'); sys.exit()\n"
        "if '--proxy' not in args: print('Northline Notes\\n200'); sys.exit()\n"
        "target=next(a for a in args if a.startswith('https://') and 'gateway.example' not in a)\n"
        "auth='--config' in args\n"
        "with open(os.environ['CALLS'], 'a') as log: log.write(f'{auth} {target}\\n')\n"
        "if auth:\n"
        " assert 'private-user:private-password' in sys.stdin.read()\n"
        " if mode=='targets-down' or mode=='fallback' and target=='https://example.com/': sys.exit(28)\n"
        " print('200', end=''); sys.exit()\n"
        "if mode=='open': print('HTTP/1.1 200 Connection established\\nTarget content\\n200'); sys.exit()\n"
        "if mode in ('transport','tls-error'): print('000'); sys.exit(7 if mode=='transport' else 60)\n"
        "if mode=='disclosure': print('Proxy-Authenticate: Basic\\n407'); sys.exit(56)\n"
        "if mode=='redirect': print('HTTP/1.1 308 Permanent Redirect\\n308'); sys.exit(56)\n"
        "print('HTTP/1.1 404 Not Found\\n404'); sys.exit(56)\n"
    )
    fake.chmod(0o755)
    for name in ("curl", "openssl", "docker"):
        (binary / name).symlink_to(fake)
    calls = tmp_path / "calls"
    completed = subprocess.run(
        ["bash", str(release / "scripts/check-server.sh")],
        env={
            **os.environ,
            "PATH": f"{binary}:{os.environ['PATH']}",
            "SCENARIO": scenario,
            "CALLS": str(calls),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert (completed.returncode == 0) == (scenario in ("closed", "redirect", "fallback"))
    assert message in completed.stdout + completed.stderr
    assert "private-password" not in completed.stdout + completed.stderr
    if scenario == "fallback":
        assert calls.read_text().splitlines()[-2:] == [
            "True https://www.cloudflare.com/cdn-cgi/trace",
            "False https://www.cloudflare.com/cdn-cgi/trace",
        ]


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
