"""Claude Code (headless `claude -p`) as the coding harness."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from deleg8.agents.base import AgentResult, CodingHarness
from deleg8.shell import clean_env

READ_ONLY_TOOLS = [
    "Read",
    "Grep",
    "Glob",
    "mcp__deleg8",
    "Bash(git log:*)",
    "Bash(git diff:*)",
    "Bash(git show:*)",
    "Bash(ls:*)",
]


class ClaudeCode(CodingHarness):
    name = "claude_code"

    def _run(self, prompt: str, schema: dict, cwd: Path, tag: str, write: bool) -> AgentResult:
        cmd = [
            "claude",
            "-p",
            "--output-format",
            "json",
            "--strict-mcp-config",
            "--mcp-config",
            str(self.mcp_config_path()),
            "--json-schema",
            json.dumps(schema),
            "--append-system-prompt",
            self.persona(),
            "--max-budget-usd",
            str(self.agent_cfg.max_budget_usd),
        ]
        if self.agent_cfg.model:
            cmd += ["--model", self.agent_cfg.model]
        if write:
            cmd += ["--permission-mode", "bypassPermissions"]
        else:
            cmd += ["--allowedTools", *READ_ONLY_TOOLS, "--disallowedTools", "Edit", "Write", "NotebookEdit"]
        cmd += self.agent_cfg.extra_args

        started = time.time()
        try:
            proc = subprocess.run(
                cmd,
                input=prompt,
                cwd=cwd,
                text=True,
                capture_output=True,
                timeout=self.agent_cfg.timeout_s,
                env=clean_env(),
            )
        except subprocess.TimeoutExpired:
            return AgentResult(
                False, error=f"timed out after {self.agent_cfg.timeout_s}s", duration_s=time.time() - started
            )
        duration = time.time() - started
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError:
            log = self._log(tag, {"cmd": cmd[:3], "stdout": proc.stdout[-5000:], "stderr": proc.stderr[-5000:]})
            return AgentResult(
                False,
                error=f"unparseable output (exit {proc.returncode}): {proc.stderr[-500:]}",
                duration_s=duration,
                log_path=log,
            )
        log = self._log(tag, {"prompt": prompt, "result": out})
        data = out.get("structured_output") or {}
        ok = not out.get("is_error") and bool(data)
        return AgentResult(
            ok=ok,
            data=data,
            text=out.get("result", ""),
            cost_usd=out.get("total_cost_usd", 0.0) or 0.0,
            duration_s=duration,
            log_path=log,
            error="" if ok else f"{out.get('subtype')}: {str(out.get('result', ''))[:500]}",
        )

    def think(self, prompt, schema, cwd, tag):
        return self._run(prompt, schema, cwd, tag, write=False)

    def work(self, prompt, schema, cwd, tag):
        return self._run(prompt, schema, cwd, tag, write=True)
