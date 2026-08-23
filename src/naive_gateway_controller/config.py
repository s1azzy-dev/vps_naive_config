"""Typed and secret-safe loading of the controller ``.env`` file."""

from __future__ import annotations

import ipaddress
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from naive_gateway_controller.errors import ConfigError

_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$")
_LINUX_USER = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$")
_GATEWAY_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_URL_SAFE_CREDENTIAL = re.compile(r"^[A-Za-z0-9._~-]+$")
_PUBLIC_KEY_PREFIXES = (
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
    "sk-ecdsa-sha2-nistp256@openssh.com",
    "sk-ssh-ed25519@openssh.com",
    "ssh-ed25519",
    "ssh-rsa",
)


def _validate_hostname(value: str, *, require_dot: bool) -> str:
    if len(value) > 253 or value.startswith(".") or value.endswith(".") or ".." in value:
        raise ValueError("must be a valid hostname")
    labels = value.split(".")
    if require_dot and len(labels) < 2:
        raise ValueError("must be a valid fully-qualified hostname")
    if any(len(label) > 63 or _HOST_LABEL.fullmatch(label) is None for label in labels):
        message = (
            "must be a valid fully-qualified hostname"
            if require_dot
            else "must be a valid hostname"
        )
        raise ValueError(message)
    return value


class GatewaySettings(BaseSettings):
    """Validated values read exclusively from the selected dotenv file."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    vps_host: str = Field(validation_alias="VPS_HOST")
    vps_port: int = Field(default=22, ge=1, le=65535, validation_alias="VPS_PORT")
    vps_bootstrap_user: str = Field(default="root", validation_alias="VPS_BOOTSTRAP_USER")
    vps_user: str = Field(default="slazzy", validation_alias="VPS_USER")
    ssh_private_key: Path = Field(validation_alias="SSH_PRIVATE_KEY")
    ssh_public_key: Path | None = Field(default=None, validation_alias="SSH_PUBLIC_KEY")
    domain: str = Field(validation_alias="DOMAIN")
    acme_email: str = Field(validation_alias="ACME_EMAIL")
    gateway_repository: str = Field(
        default="https://github.com/s1azzy-dev/vps_naive_config.git",
        validation_alias="GATEWAY_REPOSITORY",
    )
    gateway_ref: str = Field(default="main", validation_alias="GATEWAY_REF")
    naive_user: str | None = Field(default=None, validation_alias="NAIVE_USER")
    naive_password: SecretStr | None = Field(default=None, validation_alias="NAIVE_PASSWORD")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Ignore ambient environment variables; the selected file is authoritative."""
        del settings_cls, env_settings, file_secret_settings
        return init_settings, dotenv_settings

    @field_validator(
        "vps_host",
        "vps_bootstrap_user",
        "vps_user",
        "domain",
        "acme_email",
        "gateway_repository",
        "gateway_ref",
        mode="before",
    )
    @classmethod
    def required_text(cls, value: object) -> object:
        """Reject explicit empty required values instead of accepting them as defaults."""
        if isinstance(value, str) and not value.strip():
            raise ValueError("is required")
        return value

    @field_validator("ssh_private_key", mode="before")
    @classmethod
    def required_private_key(cls, value: object) -> object:
        """Reject an empty key path before ``Path('')`` becomes the current directory."""
        if not isinstance(value, str) or not value.strip():
            raise ValueError("is required")
        return value

    @field_validator("ssh_public_key", "naive_user", "naive_password", mode="before")
    @classmethod
    def empty_is_none(cls, value: object) -> object:
        """Treat documented optional blank dotenv values as absent."""
        return None if value == "" else value

    @field_validator("vps_host")
    @classmethod
    def valid_vps_host(cls, value: str) -> str:
        """Accept an IP literal or a syntactically safe DNS hostname."""
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            return _validate_hostname(value, require_dot=False)

    @field_validator("vps_bootstrap_user", "vps_user")
    @classmethod
    def valid_linux_user(cls, value: str) -> str:
        """Require a conservative Linux account name."""
        if _LINUX_USER.fullmatch(value) is None:
            raise ValueError("must be a safe Linux username")
        return value

    @field_validator("domain")
    @classmethod
    def valid_domain(cls, value: str) -> str:
        """Require a fully-qualified public hostname."""
        return _validate_hostname(value, require_dot=True)

    @field_validator("acme_email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        """Validate the intentionally conservative ACME contact format."""
        if _EMAIL.fullmatch(value) is None:
            raise ValueError("must be a valid email address")
        return value

    @field_validator("gateway_repository")
    @classmethod
    def valid_repository(cls, value: str) -> str:
        """Allow HTTPS, ssh://, or Git's SCP-like SSH repository syntax."""
        if any(character.isspace() for character in value):
            raise ValueError("must be a non-empty URL without whitespace")
        if not (value.startswith(("https://", "ssh://")) or re.match(r"^git@[^:]+:.+", value)):
            raise ValueError("must use https://, ssh://, or Git SSH syntax")
        return value

    @field_validator("gateway_ref")
    @classmethod
    def valid_ref(cls, value: str) -> str:
        """Reject ambiguous or shell-unsafe repository references."""
        if _GATEWAY_REF.fullmatch(value) is None or ".." in value:
            raise ValueError("must be a non-empty safe branch, tag, or commit")
        return value

    @field_validator("naive_user")
    @classmethod
    def valid_naive_user(cls, value: str | None) -> str | None:
        """Keep the username safe for an HTTPS userinfo component."""
        if value is not None and _URL_SAFE_CREDENTIAL.fullmatch(value) is None:
            raise ValueError("must be URL-safe")
        return value

    @field_validator("naive_password")
    @classmethod
    def valid_naive_password(cls, value: SecretStr | None) -> SecretStr | None:
        """Keep the password safe for an HTTPS userinfo component."""
        if value is not None and _URL_SAFE_CREDENTIAL.fullmatch(value.get_secret_value()) is None:
            raise ValueError("must be URL-safe")
        return value

    @model_validator(mode="after")
    def validate_cross_field_contract(self) -> Self:
        """Validate values that depend on more than one field or on local files."""
        if self.vps_bootstrap_user == self.vps_user:
            raise ValueError("VPS_BOOTSTRAP_USER and VPS_USER must be different")
        if (self.naive_user is None) != (self.naive_password is None):
            raise ValueError("NAIVE_USER and NAIVE_PASSWORD must both be set or both be empty")
        self._validate_key_file(self.ssh_private_key, "SSH_PRIVATE_KEY")
        self._validate_public_key(self.public_key_path)
        return self

    @property
    def public_key_path(self) -> Path:
        """Return the explicit public key path or the documented derived path."""
        return self.ssh_public_key or Path(f"{self.ssh_private_key}.pub")

    @staticmethod
    def _validate_key_file(path: Path, name: str) -> None:
        if not path.is_absolute():
            raise ValueError(f"{name} must be an absolute path")
        if not path.is_file() or not os.access(path, os.R_OK):
            raise ValueError(f"{name} must be a readable file")

    @classmethod
    def _validate_public_key(cls, path: Path) -> None:
        cls._validate_key_file(path, "SSH_PUBLIC_KEY")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise ValueError("SSH_PUBLIC_KEY must be a readable file") from error
        if len(lines) != 1:
            raise ValueError("SSH_PUBLIC_KEY must contain exactly one key")
        if not lines[0].startswith(tuple(f"{prefix} " for prefix in _PUBLIC_KEY_PREFIXES)):
            raise ValueError("SSH_PUBLIC_KEY is not a supported OpenSSH public key")
        try:
            completed = subprocess.run(
                ["ssh-keygen", "-lf", str(path)],
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as error:
            raise ValueError("ssh-keygen is required to validate SSH_PUBLIC_KEY") from error
        if completed.returncode != 0:
            raise ValueError("SSH_PUBLIC_KEY is not a valid OpenSSH public key")


def _format_validation_error(error: ValidationError, config_path: Path) -> str:
    messages: list[str] = []
    for item in error.errors(include_input=False, include_url=False):
        location = ".".join(str(part) for part in item["loc"])
        message = str(item["msg"]).removeprefix("Value error, ")
        if message == "Field required":
            message = f"is required in {config_path}"
        messages.append(f"{location}: {message}" if location else message)
    return "\n".join(dict.fromkeys(messages))


def load_settings(config_path: Path) -> GatewaySettings:
    """Load and validate one mode-0600 dotenv file without leaking field values."""
    if not config_path.is_file():
        raise ConfigError(f"configuration file not found: {config_path} (run: make init)")
    mode = stat.S_IMODE(config_path.stat().st_mode)
    if mode != 0o600:
        raise ConfigError(f"{config_path} must have mode 0600 (found {mode:o})")
    try:
        return GatewaySettings(_env_file=config_path, _env_file_encoding="utf-8")
    except ValidationError as error:
        raise ConfigError(_format_validation_error(error, config_path)) from error
