from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from naive_gateway_controller.config import load_settings
from naive_gateway_controller.errors import ConfigError


def test_valid_config_and_documented_defaults(
    config_factory: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = config_factory(VPS_PORT="", VPS_BOOTSTRAP_USER="", VPS_USER="")
    text = config.read_text(encoding="utf-8")
    text = (
        text.replace("VPS_PORT=\n", "")
        .replace("VPS_BOOTSTRAP_USER=\n", "")
        .replace("VPS_USER=\n", "")
    )
    config.write_text(text, encoding="utf-8")
    monkeypatch.setenv("VPS_HOST", "ambient.example.invalid")

    settings = load_settings(config)

    assert settings.vps_host == "203.0.113.10"
    assert settings.vps_port == 22
    assert settings.vps_bootstrap_user == "root"
    assert settings.vps_user == "slazzy"


def test_public_key_path_is_derived(config_factory: Callable[..., Path], private_key: Path) -> None:
    config = config_factory(SSH_PUBLIC_KEY="")

    settings = load_settings(config)

    assert settings.public_key_path == private_key.with_suffix(".pub")


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"VPS_HOST": ""}, "VPS_HOST: is required"),
        ({"VPS_PORT": "70000"}, "VPS_PORT: Input should be less than or equal to 65535"),
        ({"VPS_USER": "invalid user"}, "VPS_USER: must be a safe Linux username"),
        (
            {"VPS_BOOTSTRAP_USER": "root", "VPS_USER": "root"},
            "VPS_BOOTSTRAP_USER and VPS_USER must be different",
        ),
        ({"DOMAIN": "invalid_domain"}, "DOMAIN: must be a valid fully-qualified hostname"),
        ({"ACME_EMAIL": "invalid-email"}, "ACME_EMAIL: must be a valid email address"),
        (
            {"NAIVE_USER": "explicit-user", "NAIVE_PASSWORD": ""},
            "NAIVE_USER and NAIVE_PASSWORD must both be set or both be empty",
        ),
    ],
)
def test_invalid_values_are_rejected(
    config_factory: Callable[..., Path],
    overrides: dict[str, str],
    expected: str,
) -> None:
    with pytest.raises(ConfigError, match=expected):
        load_settings(config_factory(**overrides))


def test_missing_private_key_is_rejected(
    config_factory: Callable[..., Path], tmp_path: Path
) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(ConfigError, match="SSH_PRIVATE_KEY must be a readable file"):
        load_settings(
            config_factory(
                SSH_PRIVATE_KEY=str(missing), SSH_PUBLIC_KEY=str(missing.with_suffix(".pub"))
            ),
        )


def test_invalid_public_key_is_rejected(
    config_factory: Callable[..., Path], tmp_path: Path
) -> None:
    public_key = tmp_path / "invalid.pub"
    public_key.write_text("not-a-key\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="SSH_PUBLIC_KEY is not a supported OpenSSH public key"):
        load_settings(config_factory(SSH_PUBLIC_KEY=str(public_key)))


def test_config_file_must_exist_and_be_private(
    config_factory: Callable[..., Path],
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigError, match="configuration file not found"):
        load_settings(tmp_path / "missing.env")
    config = config_factory()
    config.chmod(0o644)
    with pytest.raises(ConfigError, match="must have mode 0600"):
        load_settings(config)


def test_validation_error_never_contains_password(config_factory: Callable[..., Path]) -> None:
    secret = "contains forbidden spaces"
    with pytest.raises(ConfigError) as captured:
        load_settings(config_factory(NAIVE_USER="user", NAIVE_PASSWORD=secret))
    assert secret not in str(captured.value)
