"""Refuse conditional SSH policy, including recursively included configuration."""

from __future__ import annotations

import glob
import shlex
import sys
from pathlib import Path


def check_config(path: Path, include_root: Path, ancestors: tuple[Path, ...] = ()) -> None:
    """Read OpenSSH Include directives without executing configuration content."""
    resolved = path.resolve(strict=True)
    if resolved in ancestors:
        raise ValueError("recursive SSH Include is unsupported")
    for line in resolved.read_text(encoding="utf-8").splitlines():
        words = shlex.split(line, comments=True)
        if not words:
            continue
        directive, separator, argument = words[0].partition("=")
        arguments = ([argument] if separator and argument else []) + words[1:]
        if not separator and arguments and arguments[0].startswith("="):
            arguments = ([arguments[0][1:]] if arguments[0][1:] else []) + arguments[1:]
        directive = directive.lower()
        if directive == "match":
            raise ValueError(
                "active SSH Match rules require explicit migration before provisioning"
            )
        if directive == "include":
            for pattern in arguments:
                candidate = Path(pattern)
                if not candidate.is_absolute():
                    candidate = include_root / candidate
                # Match OpenSSH glob(3) dotfile semantics; Path.glob includes hidden files.
                for included in sorted(glob.glob(str(candidate))):  # noqa: PTH207
                    check_config(Path(included), include_root, (*ancestors, resolved))


if __name__ == "__main__":
    try:
        check_config(
            Path(sys.argv[1]), Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/etc/ssh")
        )
    except (OSError, ValueError):
        print(
            "SSH policy: ERROR: unreadable, recursive or conditional Match configuration",
            file=sys.stderr,
        )
        sys.exit(1)
    print("Unconditional SSH policy: OK")
