"""Validate Git transports without accepting credentials in repository URLs."""

from __future__ import annotations

import re
import sys
from urllib.parse import urlsplit


def validate_repository_url(value: str) -> str:
    """Keep public HTTPS and username-only SSH URLs; errors never echo input."""
    if (
        not value
        or any(character.isspace() or ord(character) < 32 for character in value)
        or "\\" in value
    ):
        raise ValueError("repository must be a URL without whitespace or backslashes")
    if re.fullmatch(r"git@[A-Za-z0-9][A-Za-z0-9.-]*:[A-Za-z0-9._~/-]+", value):
        return value
    try:
        parsed = urlsplit(value)
        valid_port = parsed.port is None or 1 <= parsed.port <= 65535
    except ValueError:
        raise ValueError("repository URL has an invalid authority or port") from None
    if (
        parsed.scheme not in {"https", "ssh"}
        or not parsed.hostname
        or not valid_port
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "repository must use HTTPS or SSH with a valid host and no query or fragment"
        )
    if "%" in parsed.netloc or parsed.password is not None:
        raise ValueError("repository URL must not contain credentials or encoded userinfo")
    if parsed.scheme == "https" and parsed.username is not None:
        raise ValueError("HTTPS repository URL must not contain userinfo")
    if (
        parsed.scheme == "ssh"
        and parsed.username is not None
        and re.fullmatch(r"[A-Za-z0-9._-]+", parsed.username) is None
    ):
        raise ValueError("SSH repository URL may contain only a non-password username")
    if re.fullmatch(r"[A-Za-z0-9.:-]+", parsed.hostname) is None:
        raise ValueError("repository URL host is invalid")
    return value


if __name__ == "__main__":
    try:
        validate_repository_url(sys.stdin.read().removesuffix("\n"))
    except ValueError:
        print(
            "Repository URL is unsafe; use public HTTPS or SSH deploy-key access.", file=sys.stderr
        )
        sys.exit(1)
