from __future__ import annotations

import importlib
import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def runtime_modules(monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, ModuleType, ModuleType]:
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    return tuple(
        importlib.import_module(name)
        for name in ("runtime_state", "backup_runtime", "restore_runtime")
    )


def release(root: Path, commit: str) -> Path:
    path = root / "releases" / commit
    path.mkdir(parents=True)
    (path / ".release-complete").write_text(f"{commit}\n")
    return path


@pytest.mark.parametrize("candidate_started", [False, True])
def test_failed_updates_recover_env_release_and_container(
    runtime_modules: tuple[ModuleType, ModuleType, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    candidate_started: bool,
) -> None:
    module, _, _ = runtime_modules
    root = tmp_path / "gateway"
    config = tmp_path / "config"
    config.mkdir()
    old = release(root, "a" * 40)
    candidate = release(root, "b" * 40)
    state = module.RuntimeState(root, config)
    old_env = b"DOMAIN=old.example\nNAIVE_USER=old-user\nNAIVE_PASSWORD=old-secret\n"
    new_env = b"DOMAIN=new.example\nNAIVE_USER=new-user\nNAIVE_PASSWORD=new-secret\n"
    module.atomic_write(state.env, old_env)
    module.atomic_write(config / "gateway.env.pending", new_env)
    state.current.symlink_to(old)
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    state.begin(candidate)
    assert (state.recovery / "previous.env").read_bytes() == old_env
    module.atomic_write(state.env, new_env)
    if candidate_started:
        state.compose(candidate, state.env, ["up", "-d"])
    # A new controller process must use the on-disk snapshot, not old in-memory facts.
    module.RuntimeState(root, config).recover()
    assert state.env.read_bytes() == old_env
    assert state.current.resolve() == old
    assert str(old) in calls[-1]
    assert "--wait" in calls[-1]
    assert not state.recovery.exists()
    assert (config / "gateway.env.pending").read_bytes() == new_env


def test_first_failed_deploy_stops_candidate_and_keeps_retry_credentials(
    runtime_modules: tuple[ModuleType, ModuleType, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, _, _ = runtime_modules
    config = tmp_path / "config"
    config.mkdir()
    candidate = release(tmp_path / "gateway", "b" * 40)
    state = module.RuntimeState(candidate.parent.parent, config)
    module.atomic_write(config / "gateway.env.pending", b"NAIVE_PASSWORD=saved-first-secret\n")
    state.begin(candidate)
    module.atomic_write(state.env, b"NAIVE_PASSWORD=saved-first-secret\n")
    calls: list[list[str]] = []
    monkeypatch.setattr(module.subprocess, "run", lambda command, **_kwargs: calls.append(command))
    state.recover()
    assert "down" in calls[-1]
    assert "--volumes" not in calls[-1]
    assert not state.env.exists()
    assert not state.current.exists()
    assert (config / "gateway.env.pending").read_bytes() == b"NAIVE_PASSWORD=saved-first-secret\n"


def test_failed_rollback_preserves_private_recovery_material(
    runtime_modules: tuple[ModuleType, ModuleType, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, _, _ = runtime_modules
    root, config = tmp_path / "gateway", tmp_path / "config"
    config.mkdir()
    old, candidate = release(root, "a" * 40), release(root, "b" * 40)
    state = module.RuntimeState(root, config)
    state.current.symlink_to(old)
    module.atomic_write(state.env, b"old")
    module.atomic_write(config / "gateway.env.pending", b"new")
    state.begin(candidate)

    def fail_run(command: list[str], **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(module.subprocess, "run", fail_run)
    with pytest.raises(subprocess.CalledProcessError):
        state.recover()
    assert (state.recovery / "previous.env").read_bytes() == b"old"
    assert state.recovery.stat().st_mode & 0o777 == 0o700
    assert (state.recovery / "previous.env").stat().st_mode & 0o777 == 0o600


def test_successful_commit_retains_previous_env_and_release(
    runtime_modules: tuple[ModuleType, ModuleType, ModuleType],
    tmp_path: Path,
) -> None:
    module, _, _ = runtime_modules
    root, config = tmp_path / "gateway", tmp_path / "config"
    config.mkdir()
    old, candidate = release(root, "a" * 40), release(root, "b" * 40)
    state = module.RuntimeState(root, config)
    state.current.symlink_to(old)
    module.atomic_write(state.env, b"old")
    module.atomic_write(config / "gateway.env.pending", b"new")
    state.begin(candidate)
    module.atomic_write(state.env, b"new")
    state.commit()
    assert state.current.resolve() == candidate
    assert (config / "previous-deployment/previous.env").read_bytes() == b"old"
    assert old.is_dir()
    assert not state.recovery.exists()


@pytest.mark.parametrize("acceptance_fails", [False, True])
def test_autonomous_backup_restore_preserves_secrets_images_and_certificates(
    runtime_modules: tuple[ModuleType, ModuleType, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    acceptance_fails: bool,
) -> None:
    module, backup, restore = runtime_modules
    old = release(tmp_path / "old", "a" * 40)
    for name in backup.RUNTIME_FILES:
        if name == ".release-complete":
            continue
        source = ROOT / name
        target = old / name
        if source.is_dir():
            shutil.copytree(source, target)
        elif source.is_file():
            shutil.copy2(source, target)
        else:
            target.write_text("runtime fixture\n")
    env = tmp_path / "old.env"
    secret = b"DOMAIN=saved.example\nACME_EMAIL=admin@example.com\nNAIVE_USER=saved-user\nNAIVE_PASSWORD=saved-secret\n"
    module.atomic_write(env, secret)
    calls: list[list[str]] = []
    restored_volumes: list[bytes] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        output = ""
        if command[:3] == ["docker", "image", "inspect"]:
            output = "sha256:" + "1" * 64
        elif command[:3] == ["docker", "image", "save"]:
            Path(command[command.index("--output") + 1]).write_bytes(b"saved-image")
        elif command[:3] == ["docker", "image", "load"]:
            assert Path(command[command.index("--input") + 1]).read_bytes() == b"saved-image"
        elif command[:2] == ["docker", "run"]:
            mount = next(argument for argument in command if argument.startswith("type=bind,src="))
            stage = Path(mount.split("src=", 1)[1].split(",dst=", 1)[0])
            name = Path(
                command[command.index("-czf") + 1]
                if "-czf" in command
                else command[command.index("-xzf") + 1]
            ).name
            if "-czf" in command:
                with tarfile.open(stage / name, "w:gz") as bundle:
                    member = tarfile.TarInfo("certificate-private-key")
                    data = b"saved-certificate-private-key"
                    member.size = len(data)
                    member.mode = 0o600
                    bundle.addfile(member, io.BytesIO(data))
            else:
                with tarfile.open(stage / name, "r:gz") as bundle:
                    stream = bundle.extractfile("certificate-private-key")
                    assert stream is not None
                    restored_volumes.append(stream.read())
        elif command[0] == "bash" and acceptance_fails:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    archive = backup.create_backup(old, env, tmp_path / "backups")
    assert archive.stat().st_mode & 0o777 == 0o600
    assert archive.parent.stat().st_mode & 0o777 == 0o700
    with tarfile.open(archive, "r:gz") as bundle:
        assert all(".git/config" not in name for name in bundle.getnames())
        manifest_file = bundle.extractfile("manifest.json")
        assert manifest_file is not None
        assert json.load(manifest_file)["image_id"] == "sha256:" + "1" * 64
    root, config = tmp_path / "restored", tmp_path / "restored-config"
    if acceptance_fails:
        with pytest.raises(subprocess.CalledProcessError):
            restore.restore_backup(archive, root, config, "saved.example")
        assert not (root / "current").exists()
        assert not (config / "gateway.env").exists()
        assert sum(command[:3] == ["docker", "volume", "rm"] for command in calls) == 2
    else:
        restore.restore_backup(archive, root, config, "saved.example")
        assert (config / "gateway.env").read_bytes() == secret
        assert (root / "current").resolve().name == "a" * 40
        assert (root / "current/.runtime-env-path").read_text() == f"{config / 'gateway.env'}\n"
        assert (config / "gateway.env").stat().st_mode & 0o777 == 0o600
    assert archive.is_file()
    assert restored_volumes == [b"saved-certificate-private-key"] * 2
    assert not any(
        command[0] == "git" or "build" in command or "pull" in command for command in calls
    )


@pytest.mark.parametrize("member_name", ["../escape", "/absolute", "release/../../escape"])
def test_restore_rejects_archive_path_traversal(
    runtime_modules: tuple[ModuleType, ModuleType, ModuleType],
    tmp_path: Path,
    member_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, restore = runtime_modules
    archive = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        member = tarfile.TarInfo(member_name)
        member.size = 1
        bundle.addfile(member, io.BytesIO(b"x"))
    archive.chmod(0o600)
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(restore.subprocess, "run", fake_run)
    with pytest.raises(ValueError, match="unsafe backup"):
        restore.restore_backup(archive, tmp_path / "runtime", tmp_path / "config", "saved.example")
    assert not (tmp_path / "escape").exists()
    assert not any(command[:3] == ["docker", "image", "load"] for command in commands)
