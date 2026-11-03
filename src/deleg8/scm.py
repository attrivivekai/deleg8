"""Source control + CI: workspaces, branches, commits, pull requests, checks and merges (git + gh)."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from deleg8.config import Config, RepoConfig
from deleg8.shell import CommandError, gh_json, run


def slugify(text: str, n: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:n].rstrip("-")


@dataclass
class CheckResult:
    state: str  # pass | fail | pending | none
    summary: str = ""
    failed_logs: str = ""


class Workspace:
    """A dedicated clone of a repo that the AI employee works in."""

    def __init__(self, cfg: Config, repo: RepoConfig):
        self.cfg, self.repo = cfg, repo
        self.path = cfg.workspace / repo.name

    def git(self, *args: str, check: bool = True) -> str:
        return run(["git", *args], cwd=self.path, check=check).stdout.strip()

    def prepare(self, branch: str) -> None:
        if not (self.path / ".git").exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            run(["git", "clone", self.repo.clone_url, str(self.path)])
            self.git("config", "user.name", f"{self.cfg.employee.name} (deleg8)")
        self.git("fetch", "origin", "--prune")
        self.git("reset", "--hard")
        self.git("clean", "-fd")
        remote = f"origin/{branch}"
        if self.git("ls-remote", "--heads", "origin", branch, check=False):
            self.git("checkout", "-B", branch, remote)  # resume an existing PR branch
        else:
            self.git("checkout", "-B", branch, f"origin/{self.repo.default_branch}")
        for cmd in self.repo.setup:
            run(cmd, cwd=self.path, timeout=900)

    def run_checks(self) -> tuple[bool, str]:
        out = []
        for cmd in self.repo.checks:
            p = run(cmd, cwd=self.path, check=False, timeout=900)
            out.append(f"$ {cmd}\n(exit {p.returncode})\n{(p.stdout + p.stderr)[-3000:]}")
            if p.returncode != 0:
                return False, "\n\n".join(out)
        return True, "\n\n".join(out)

    def has_changes(self) -> bool:
        return bool(self.git("status", "--porcelain"))

    def diff_vs_base(self) -> str:
        return self.git("diff", f"origin/{self.repo.default_branch}...HEAD")

    def diffstat_vs_base(self) -> str:
        return self.git("diff", "--stat", f"origin/{self.repo.default_branch}...HEAD")

    def changed_files(self) -> list[str]:
        out = self.git("diff", "--name-only", f"origin/{self.repo.default_branch}...HEAD")
        return out.splitlines() if out else []

    def commit_and_push(self, branch: str, message: str) -> bool:
        if self.has_changes():
            self.git("add", "-A")
            self.git("commit", "-m", message)
        ahead = self.git("rev-list", "--count", f"origin/{self.repo.default_branch}..HEAD")
        if ahead == "0":
            return False
        self.git("push", "-f", "-u", "origin", branch)
        return True


class GitHubPRs:
    def __init__(self, repo: RepoConfig):
        self.repo = repo
        self.r = ["-R", repo.github]

    def find(self, branch: str) -> dict | None:
        prs = gh_json(["pr", "list", *self.r, "--head", branch, "--state", "all", "--json", "number,url,state,isDraft"])
        return prs[0] if prs else None

    def open(self, branch: str, title: str, body: str) -> dict:
        existing = self.find(branch)
        if existing and existing["state"] == "OPEN":
            run(["gh", "pr", "edit", str(existing["number"]), *self.r, "--body-file", "-"], input=body)
            return existing
        run(
            [
                "gh",
                "pr",
                "create",
                *self.r,
                "--head",
                branch,
                "--base",
                self.repo.default_branch,
                "--title",
                title,
                "--body-file",
                "-",
            ],
            input=body,
        )
        return self.find(branch)

    def comment(self, number: int, body: str) -> None:
        run(["gh", "pr", "comment", str(number), *self.r, "--body-file", "-"], input=body)

    def state(self, number: int) -> str:
        return gh_json(["pr", "view", str(number), *self.r, "--json", "state"])["state"]

    def wait_for_checks(self, number: int, timeout_s: int) -> CheckResult:
        deadline = time.time() + timeout_s
        time.sleep(10)  # give Actions a moment to register the runs
        while time.time() < deadline:
            p = run(["gh", "pr", "checks", str(number), *self.r, "--json", "name,state,bucket,link"], check=False)
            checks = gh_json_safe(p.stdout)
            if not checks:
                if "no checks" in (p.stderr + p.stdout).lower() and time.time() > deadline - timeout_s + 90:
                    return CheckResult("none", "no CI checks configured")
                time.sleep(10)
                continue
            buckets = {c["bucket"] for c in checks}
            summary = ", ".join(f"{c['name']}={c['bucket']}" for c in checks)
            if "fail" in buckets or "cancel" in buckets:
                failed = [c for c in checks if c["bucket"] in ("fail", "cancel")]
                return CheckResult("fail", summary, self.failed_logs(number, failed))
            if buckets <= {"pass", "skipping"}:
                return CheckResult("pass", summary)
            time.sleep(15)
        return CheckResult("pending", "timed out waiting for CI")

    def failed_logs(self, number: int, failed_checks: list[dict] | None = None) -> str:
        """Logs for failed checks: GitHub Actions via gh, CircleCI via its API, others as name + link."""
        from deleg8 import circleci

        parts = []
        for c in failed_checks or []:
            link = c.get("link") or ""
            if circleci.is_circleci(link):
                try:
                    parts.append(f"### CircleCI: {c['name']}\n{circleci.failed_step_log(link)}")
                except Exception as e:  # never let log fetching break the workflow
                    parts.append(f"### CircleCI: {c['name']} failed ({link}); log fetch error: {e}")
            elif "github.com" not in link:
                parts.append(f"### {c['name']} failed: {link}")
        actions = self._actions_failed_logs(number)
        if actions:
            parts.insert(0, f"### GitHub Actions\n{actions}")
        return "\n\n".join(parts)[-8000:]

    def _actions_failed_logs(self, number: int) -> str:
        branch = gh_json(["pr", "view", str(number), *self.r, "--json", "headRefName"])["headRefName"]
        runs = (
            gh_json(
                [
                    "run",
                    "list",
                    *self.r,
                    "--branch",
                    branch,
                    "--limit",
                    "5",
                    "--json",
                    "databaseId,conclusion",
                ]
            )
            or []
        )
        for r in runs:
            if r.get("conclusion") == "failure":
                p = run(["gh", "run", "view", str(r["databaseId"]), *self.r, "--log-failed"], check=False)
                return (p.stdout or p.stderr)[-6000:]
        return ""

    def merge(self, number: int) -> None:
        run(["gh", "pr", "merge", str(number), *self.r, "--squash", "--delete-branch"])

    def latest_deploy(self, workflow: str = "deploy.yml") -> dict | None:
        try:
            runs = gh_json(
                [
                    "run",
                    "list",
                    *self.r,
                    "--workflow",
                    workflow,
                    "--limit",
                    "1",
                    "--json",
                    "databaseId,status,conclusion,url,headSha",
                ]
            )
        except CommandError:
            return None
        return runs[0] if runs else None


def gh_json_safe(text: str):
    import json

    try:
        return json.loads(text) if text.strip() else None
    except json.JSONDecodeError:
        return None
