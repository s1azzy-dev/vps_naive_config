from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "provisioning/files/sshd_policy.py"


@pytest.mark.parametrize(
    "directive", ["Match User root", "mAtCh Address 192.0.2.0/24", "Match=User root"]
)
@pytest.mark.parametrize("separator", [" ", "=", " =", " = "])
def test_conditional_policy_in_transitive_include_is_rejected(
    tmp_path: Path, directive: str, separator: str
) -> None:
    config = tmp_path / "sshd_config"
    config.write_text(f'Include{separator}"first.conf"\n')
    (tmp_path / "first.conf").write_text(f"Include={tmp_path}/nested/*.conf\n")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested/root.conf").write_text(f"{directive}\n PermitRootLogin yes\n")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(config), str(tmp_path)], check=False, capture_output=True
    )
    assert result.returncode == 1


def test_unconditional_policy_and_comments_pass(tmp_path: Path) -> None:
    config = tmp_path / "sshd_config"
    config.write_text("# Match User root\nInclude absent/*.conf\nPermitRootLogin no\n")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(config), str(tmp_path)], check=False, capture_output=True
    )
    assert result.returncode == 0


def test_recursive_include_is_a_safe_failure(tmp_path: Path) -> None:
    config = tmp_path / "sshd_config"
    config.write_text("Include sshd_config\n")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(config), str(tmp_path)], check=False, capture_output=True
    )
    assert result.returncode == 1
