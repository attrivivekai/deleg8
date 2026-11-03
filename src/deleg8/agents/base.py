"""Coding-harness adapters. A harness is used in two modes:

* think(): read-only reasoning with research tools (planning, code review, reports)
* work():  full read/write/shell access inside a repo workspace (implementing tickets)

Both return structured JSON validated against a schema, plus cost and a transcript log.
"""

from __future__ import annotations

import json
import re
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deleg8.config import AgentConfig, Config


@dataclass
class AgentResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    cost_usd: float = 0.0
    duration_s: float = 0.0
    log_path: str = ""
    error: str = ""


class CodingHarness(ABC):
    name = "base"

    def __init__(self, cfg: Config, agent_cfg: AgentConfig):
        self.cfg = cfg
        self.agent_cfg = agent_cfg
        self.log_dir = cfg.state_dir / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def persona(self) -> str:
        e = self.cfg.employee
        return (
            f"You are {e.name}, a {e.title} at deleg8. You work autonomously from tickets, like a careful "
            "junior engineer: you research before acting, keep changes small and focused, follow the repo's "
            "AGENTS.md/CLAUDE.md conventions, write tests, and never guess when requirements are unclear: "
            "you ask. Database and warehouse access is read-only. Never paste personal data (emails) into "
            "outputs; report counts or anonymized examples.\n\n"
            "Company research tools are available as MCP tools (server `deleg8`) or via the shell:\n"
            f"  {self.tool_cli} wiki-search '<query>' | wiki-read <path> | wiki-list\n"
            f"  {self.tool_cli} db-list | db-schema <db> | db-query <db> '<SELECT ...>'\n"
            f"  {self.tool_cli} ticket-get <id> | ticket-search '<query>'"
        )

    @property
    def tool_cli(self) -> str:
        return f"{sys.executable} -m deleg8.cli --config {self.cfg.path} tool"

    def mcp_config_path(self) -> Path:
        path = self.cfg.state_dir / "mcp.json"
        path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "deleg8": {
                            "command": sys.executable,
                            "args": ["-m", "deleg8.mcp_server", "--config", str(self.cfg.path)],
                        }
                    }
                },
                indent=2,
            )
        )
        return path

    def _log(self, tag: str, payload: dict) -> str:
        path = self.log_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{tag}.json"
        path.write_text(json.dumps(payload, indent=2, default=str))
        return str(path)

    @abstractmethod
    def think(self, prompt: str, schema: dict, cwd: Path, tag: str) -> AgentResult: ...

    @abstractmethod
    def work(self, prompt: str, schema: dict, cwd: Path, tag: str) -> AgentResult: ...


def extract_json_block(text: str) -> dict | None:
    """Pull the last JSON object out of free text (fenced ```json block preferred)."""
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = blocks[::-1] or [text[text.rfind("{", 0, text.rfind("}")) :]]
    for c in candidates:
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            continue
    # last resort: scan for the largest balanced object
    for start in [m.start() for m in re.finditer(r"\{", text)]:
        try:
            return json.loads(text[start : text.rfind("}") + 1])
        except json.JSONDecodeError:
            continue
    return None


def make_harness(cfg: Config, role: str = "coding") -> CodingHarness:
    agent_cfg = cfg.coding_agent if role == "coding" else cfg.brain
    if agent_cfg.provider == "claude_code":
        from deleg8.agents.claude_code import ClaudeCode

        return ClaudeCode(cfg, agent_cfg)
    if agent_cfg.provider == "pi":
        from deleg8.agents.pi import Pi

        return Pi(cfg, agent_cfg)
    raise ValueError(f"unknown coding harness {agent_cfg.provider!r}")
