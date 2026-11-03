"""Configuration: one YAML file describes the employee, its tools and its policies."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Employee:
    name: str = "Dex"
    title: str = "Junior Software Engineer (AI)"

    @property
    def signature(self) -> str:
        return f"🤖 **{self.name}** · deleg8 {self.title}"


@dataclass
class RepoConfig:
    name: str
    github: str  # owner/repo
    default_branch: str = "main"
    setup: list[str] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    deploy_url: str = ""

    @property
    def clone_url(self) -> str:
        return f"git@github.com:{self.github}.git"


@dataclass
class AgentConfig:
    provider: str = "claude_code"  # claude_code | pi | dsh
    model: str = ""
    max_budget_usd: float = 5.0
    timeout_s: int = 1800
    extra_args: list[str] = field(default_factory=list)
    command: list[str] = field(default_factory=list)  # override the harness executable (e.g. node + bin.js)
    env: dict[str, str] = field(default_factory=dict)  # extra env vars for the harness process
    env_file: str = ""  # KEY=VALUE file merged into the env (e.g. a local model's API key)
    permission_mode: str = ""  # dsh: sandbox mode for work() (read-only is always used for think())

    def child_env(self) -> dict[str, str]:
        from deleg8.shell import clean_env

        env = {}
        if self.env_file:
            path = Path(os.path.expanduser(self.env_file))
            if path.is_file():
                for line in path.read_text().splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        env[k.removeprefix("export ").strip()] = v.strip().strip('"').strip("'")
        env.update({k: os.path.expanduser(str(v)) for k, v in self.env.items()})
        return clean_env(env)


@dataclass
class Policy:
    auto_merge: bool = True
    ai_review: bool = True
    wait_for_ci: bool = True
    ci_timeout_s: int = 1200
    max_fix_attempts: int = 2
    max_review_rounds: int = 2
    max_tasks_per_run: int = 10
    max_tasks_per_epic: int = 8


@dataclass
class Config:
    root: Path
    employee: Employee
    pm: dict[str, Any]
    repos: list[RepoConfig]
    wiki_dirs: list[Path]
    databases: dict[str, dict[str, str]]
    coding_agent: AgentConfig
    brain: AgentConfig
    policy: Policy
    workspace: Path
    path: Path

    def repo(self, name: str | None) -> RepoConfig:
        if not name:
            return self.repos[0]
        for r in self.repos:
            if name in (r.name, r.github):
                return r
        raise KeyError(f"unknown repo {name!r}; configured: {[r.name for r in self.repos]}")

    @property
    def state_dir(self) -> Path:
        d = self.root / ".deleg8"
        d.mkdir(parents=True, exist_ok=True)
        return d


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def load_config(path: str | os.PathLike | None = None, harness: str | None = None) -> Config:
    path = Path(path or os.environ.get("DELEG8_CONFIG", "deleg8.yaml")).resolve()
    raw = _expand(yaml.safe_load(path.read_text()) or {})
    root = path.parent

    def rel(p: str) -> Path:
        q = Path(p).expanduser()
        return q if q.is_absolute() else (root / q).resolve()

    dbs = {}
    for name, spec in (raw.get("knowledge", {}).get("databases") or {}).items():
        spec = dict(spec)
        url = spec["url"]
        if url.startswith(("duckdb:///", "sqlite:///")):
            scheme, p = url.split(":///", 1)
            spec["url"] = f"{scheme}:///{rel(p)}"
        dbs[name] = spec

    coding_raw = raw.get("coding_agent", {})
    brain_raw = raw.get("brain", coding_raw)
    harness = harness or os.environ.get("DELEG8_HARNESS")
    if harness:  # named preset from `harnesses:` replaces both roles (e.g. --harness dsh for local models)
        presets = raw.get("harnesses", {})
        if harness not in presets:
            raise KeyError(f"unknown harness preset {harness!r}; defined: {list(presets)}")
        coding_raw = presets[harness].get("coding_agent", presets[harness])
        brain_raw = presets[harness].get("brain", coding_raw)

    return Config(
        root=root,
        path=path,
        employee=Employee(**raw.get("employee", {})),
        pm=raw.get("pm", {"provider": "github"}),
        repos=[RepoConfig(**r) for r in raw.get("repos", [])],
        wiki_dirs=[rel(p) for p in raw.get("knowledge", {}).get("wiki_dirs", [])],
        databases=dbs,
        coding_agent=AgentConfig(**coding_raw),
        brain=AgentConfig(**brain_raw),
        policy=Policy(**raw.get("policy", {})),
        workspace=rel(raw.get("workspace", ".deleg8/workspaces")),
    )
