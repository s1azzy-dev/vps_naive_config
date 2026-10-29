from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from naive_gateway_controller import tooling
from naive_gateway_controller.errors import ToolingError

ROOT = Path(__file__).resolve().parent.parent


def test_all_provisioning_playbooks_pass_real_ansible_syntax_check() -> None:
    tooling.check_playbook_syntax(ROOT)


@pytest.mark.parametrize(
    "error",
    [OSError("cannot execute ansible"), subprocess.TimeoutExpired("ansible-playbook", 60)],
)
def test_syntax_check_execution_errors_are_safe_controller_failures(
    error: Exception,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_run(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr(tooling.subprocess, "run", fail_run)
    with pytest.raises(ToolingError, match="unable to run the local Ansible syntax check"):
        tooling.check_playbook_syntax(ROOT)


def test_found_but_unexecutable_git_is_a_tooling_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tooling.shutil, "which", lambda name: f"/broken/{name}")

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[0] == "git":
            raise OSError("Bad CPU type in executable")
        return subprocess.CompletedProcess(command, 255 if command[0] == "ssh-keygen" else 0)

    monkeypatch.setattr(tooling.subprocess, "run", fake_run)
    with pytest.raises(ToolingError, match="cannot run: git; check its architecture and PATH"):
        tooling.check_tooling(ROOT)


@pytest.mark.parametrize("installed_version", [None, "0.0.0"])
def test_declared_dependency_must_be_installed_at_its_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, installed_version: str | None
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["fixture[extra]==1.2.3"]\n[dependency-groups]\ndev = []\n'
    )

    def version(name: str) -> str:
        assert name == "fixture"
        if installed_version is None:
            raise tooling.importlib.metadata.PackageNotFoundError(name)
        return installed_version

    monkeypatch.setattr(tooling.importlib.metadata, "version", version)
    with pytest.raises(ToolingError, match="run 'make tooling'"):
        tooling._check_python_versions(tmp_path)
