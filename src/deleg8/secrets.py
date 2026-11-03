"""Secrets store: API keys/tokens live in ~/.config/deleg8/secrets.env (mode 0600), never in project YAML.

Configs reference them as ${NAME}; every deleg8 process loads this file into its environment first.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def secrets_path() -> Path:
    return Path(os.environ.get("DELEG8_SECRETS", Path.home() / ".config" / "deleg8" / "secrets.env"))


def read_secrets(path: Path | None = None) -> dict[str, str]:
    path = path or secrets_path()
    out: dict[str, str] = {}
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def load_secrets_into_env() -> None:
    for k, v in read_secrets().items():
        os.environ.setdefault(k, v)


def write_secrets(updates: dict[str, str | None], path: Path | None = None) -> dict[str, str]:
    """Set (value) or delete (None) secrets. Values may not contain newlines."""
    path = path or secrets_path()
    current = read_secrets(path)
    for k, v in updates.items():
        if not NAME_RE.match(k):
            raise ValueError(f"invalid secret name {k!r} (use UPPER_CASE letters, digits, _)")
        if v is None:
            current.pop(k, None)
            os.environ.pop(k, None)
        else:
            if "\n" in v or "\r" in v:
                raise ValueError(f"secret {k} contains a newline")
            current[k] = v
            os.environ[k] = v
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write("# deleg8 secrets (managed by the deleg8 panel). Keep private.\n")
        fh.writelines(f"{k}={v}\n" for k, v in sorted(current.items()))
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    return current


def mask(value: str) -> str:
    return "•" * 6 + value[-4:] if len(value) > 8 else "•" * len(value)
