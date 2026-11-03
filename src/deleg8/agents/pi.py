"""pi (https://github.com/badlogic/pi-mono) as the coding harness.

pi has no MCP or JSON-schema flag, so research tools are reached via the `deleg8 tool` CLI from its bash
tool, and the structured result is parsed from a final ```json block.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from deleg8.agents.base import AgentResult, CodingHarness, extract_json_block
from deleg8.shell import clean_env


class Pi(CodingHarness):
    name = "pi"

    def _run(self, prompt: str, schema: dict, cwd: Path, tag: str, write: bool) -> AgentResult:
        prompt = (
            f"{prompt}\n\nWhen you are finished, end your reply with a single ```json fenced block that "
            f"matches this JSON schema:\n{json.dumps(schema)}"
        )
        cmd = ["pi", "-p", "--no-session", "--append-system-prompt", self.persona()]
        if self.agent_cfg.model:
            cmd += ["--model", self.agent_cfg.model]
        if not write:
            cmd += ["--tools", "read,bash"]  # bash is needed for `deleg8 tool ...`; prompt forbids edits
            prompt = "READ-ONLY MODE: do not modify any files.\n\n" + prompt
        cmd += [*self.agent_cfg.extra_args, prompt]
        started = time.time()
        try:
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                text=True,
                capture_output=True,
                timeout=self.agent_cfg.timeout_s,
                env=clean_env(),
            )
        except subprocess.TimeoutExpired:
            return AgentResult(False, error="timed out", duration_s=time.time() - started)
        data = extract_json_block(proc.stdout) or {}
        log = self._log(tag, {"prompt": prompt, "stdout": proc.stdout, "stderr": proc.stderr[-4000:]})
        ok = proc.returncode == 0 and bool(data)
        return AgentResult(
            ok=ok,
            data=data,
            text=proc.stdout,
            duration_s=time.time() - started,
            log_path=log,
            error="" if ok else f"exit {proc.returncode}: {proc.stderr[-500:]}",
        )

    def think(self, prompt, schema, cwd, tag):
        return self._run(prompt, schema, cwd, tag, write=False)

    def work(self, prompt, schema, cwd, tag):
        return self._run(prompt, schema, cwd, tag, write=True)
