"""Thin subprocess helpers (the harness drives git, gh and coding agents through the shell)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

# Env vars that would make a child coding agent think it is nested inside another session.
_PARENT_SESSION_VARS = (
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_CODE_MESSAGING_SOCKET",
    "CLAUDE_CODE_MESSAGING_TOKEN",
    "CLAUDE_CODE_BRIDGE_SESSION_ID",
    "CLAUDE_CODE_SESSION_ATTENDED",
    "CLAUDE_PID",
)


class CommandError(RuntimeError):
    def __init__(self, cmd: list[str] | str, code: int, out: str, err: str):
        self.cmd, self.code, self.out, self.err = cmd, code, out, err
        super().__init__(f"command failed ({code}): {cmd}\n{err or out}"[-4000:])


def clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _PARENT_SESSION_VARS}
    env.pop("VIRTUAL_ENV", None)  # don't leak the harness venv into the workplace repo
    env.update(extra or {})
    return env


def run(
    cmd: list[str] | str,
    cwd: str | Path | None = None,
    check: bool = True,
    input: str | None = None,
    timeout: int | None = 600,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        input=input,
        text=True,
        capture_output=True,
        timeout=timeout,
        shell=isinstance(cmd, str),
        env=env or clean_env(),
    )
    if check and proc.returncode != 0:
        raise CommandError(cmd, proc.returncode, proc.stdout, proc.stderr)
    return proc


def gh_json(args: list[str], **kw: Any) -> Any:
    out = run(["gh", *args], **kw).stdout.strip()
    return json.loads(out) if out else None
