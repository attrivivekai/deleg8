"""DeepSeek Harness (dsh) as the coding harness, typically driving a LOCAL model (llama.cpp / Ollama).

How it maps onto dsh (verified against @deepseek-ai/dsh 0.1.5):
* `dsh --profile headless "<task>"`  runs one task, streams reasoning to stderr, prints the final message.
* The model comes from `agent-default-model` in `$DSH_HOME/settings.yaml`, so point DSH_HOME at a home whose
  settings follow your local llama-server (e.g. the local-ai panel's DSH home) and deleg8 uses that model.
* Sandbox: `DSH_PERMISSION_MODE` = read-only (think) / workspace-write or danger-full-access (work).
  Headless mode can't answer approval prompts, so anything outside the sandbox is denied (fails closed).
* Research tools: a per-run `--patch` overlay mounts deleg8's MCP server via `@deepseek-ai/dsh-mcp-client`,
  so the model gets `mcp__deleg8__wiki_search`, `db_query`, ... natively. The `deleg8 tool` CLI also works.
* dsh has no JSON-schema output flag, so the structured result is parsed from a final ```json block.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import yaml

from deleg8.agents.base import AgentResult, CodingHarness, extract_json_block

PERMISSION_MODES = ("read-only", "workspace-write", "danger-full-access")


class DeepSeekHarness(CodingHarness):
    name = "dsh"

    def _overlay(self) -> Path:
        """Patch overlay: Dex's persona + the deleg8 MCP server, layered over the headless profile."""
        patch = [
            {
                "id": "system-prompt",
                "config": {
                    "personaPrefix": "You are a coding agent powered by the {{model}} model.",
                    "personaSuffix": "Your working directory is {{cwd}}.\n\n" + self.persona(),
                },
            },
            {
                "insert": [
                    {
                        "id": "deleg8-mcp",
                        "name": "@deepseek-ai/dsh-mcp-client",
                        "config": {
                            "transport": "stdio",
                            "serverName": "deleg8",
                            "command": sys.executable,
                            "args": ["-m", "deleg8.mcp_server", "--config", str(self.cfg.path)],
                            "env": {},
                            "cwd": str(self.cfg.root),
                            "toolCallTimeoutMs": 120000,
                            "failOnStartupError": False,
                        },
                    }
                ]
            },
        ]
        path = self.cfg.state_dir / "dsh-overlay.yml"
        path.write_text(yaml.safe_dump(patch, sort_keys=False, allow_unicode=True))
        return path

    def base_command(self) -> list[str]:
        import os

        return [os.path.expanduser(c) for c in self.agent_cfg.command] or ["dsh"]

    def model_info(self) -> dict:
        """The model dsh will use, read from $DSH_HOME/settings.yaml (for logs and `deleg8 doctor`)."""
        env = self.agent_cfg.child_env()
        home = Path(env.get("DSH_HOME") or Path.home() / ".dsh")
        try:
            settings = yaml.safe_load((home / "settings.yaml").read_text()) or {}
        except OSError:
            return {"home": str(home), "error": "settings.yaml not found"}
        default = settings.get("agent-default-model") or {}
        provider = (settings.get("llm-pi-ai", {}).get("providers", {}) or {}).get(default.get("provider"), {})
        model = next((m for m in provider.get("models", []) if m.get("id") == default.get("model")), {})
        return {
            "home": str(home),
            "provider": default.get("provider"),
            "model": default.get("model"),
            "base_url": provider.get("baseURL"),
            "context_window": model.get("contextWindow"),
        }

    def _run(self, prompt: str, schema: dict, cwd: Path, tag: str, write: bool) -> AgentResult:
        mode = (self.agent_cfg.permission_mode or "workspace-write") if write else "read-only"
        if mode not in PERMISSION_MODES:
            return AgentResult(False, error=f"invalid permission_mode {mode!r}; use one of {PERMISSION_MODES}")
        task = (
            f"{prompt}\n\nWhen you are finished, end your reply with a single ```json fenced block that "
            f"matches this JSON schema (no other text after it):\n{json.dumps(schema)}"
        )
        if not write:
            task = "READ-ONLY MODE: research and reason only; do not modify any files.\n\n" + task
        cmd = [
            *self.base_command(),
            "--patch",
            str(self._overlay()),
            "--profile",
            "headless",
            *self.agent_cfg.extra_args,
            task,
        ]
        env = self.agent_cfg.child_env()
        env["DSH_PERMISSION_MODE"] = mode
        env.setdefault("DSH_TELEMETRY_DISABLED", "1")

        started = time.time()
        try:
            proc = subprocess.run(
                cmd, cwd=cwd, text=True, capture_output=True, timeout=self.agent_cfg.timeout_s, env=env
            )
        except subprocess.TimeoutExpired:
            return AgentResult(
                False, error=f"timed out after {self.agent_cfg.timeout_s}s", duration_s=time.time() - started
            )
        except FileNotFoundError as e:
            return AgentResult(False, error=f"dsh not found ({e}); set `command:` for this harness in deleg8.yaml")
        duration = time.time() - started
        data = extract_json_block(proc.stdout) or {}
        log = self._log(
            tag,
            {
                "model": self.model_info(),
                "permission_mode": mode,
                "prompt": task,
                "stdout": proc.stdout,
                "stderr_tail": proc.stderr[-8000:],
            },
        )
        ok = proc.returncode == 0 and bool(data)
        err = (
            ""
            if ok
            else (
                f"exit {proc.returncode}; no JSON result block in output"
                if proc.returncode == 0
                else f"exit {proc.returncode}: {proc.stderr[-500:]}"
            )
        )
        # Local models cost nothing per token; duration is still tracked in the journal.
        return AgentResult(
            ok=ok, data=data, text=proc.stdout, cost_usd=0.0, duration_s=duration, log_path=log, error=err
        )

    def think(self, prompt, schema, cwd, tag):
        return self._run(prompt, schema, cwd, tag, write=False)

    def work(self, prompt, schema, cwd, tag):
        return self._run(prompt, schema, cwd, tag, write=True)
