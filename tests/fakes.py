"""In-memory fakes so the employee's workflow can be tested without GitHub or a model."""

from __future__ import annotations

from deleg8.agents.base import AgentResult
from deleg8.models import Comment, Ticket, with_meta
from deleg8.pm.base import ProjectManager
from deleg8.scm import CheckResult


class FakePM(ProjectManager):
    def __init__(self):
        self.tickets: dict[str, Ticket] = {}
        self.next_id = 1

    def add(self, type, title, body="", assign=True, meta=None) -> Ticket:
        tid = str(self.next_id)
        self.next_id += 1
        self.tickets[tid] = Ticket(
            tid, type, title, with_meta(body, meta) if meta else body, "todo", f"https://pm/{tid}", assigned=assign
        )
        return self.tickets[tid]

    def assigned(self):
        return [t for t in self.tickets.values() if t.assigned and t.status != "done"]

    def get(self, ticket_id):
        return self.tickets[str(ticket_id)]

    def search(self, query, limit=10):
        return [t for t in self.tickets.values() if query.lower() in t.title.lower()][:limit]

    def create(self, type, title, body, parent=None, meta=None, assign=True):
        meta = dict(meta or {})
        if parent:
            meta["parent"] = str(parent)
        return self.add(type, title, body, assign, meta)

    def children(self, ticket_id):
        return [t for t in self.tickets.values() if t.parent == str(ticket_id)]

    def _post_comment(self, ticket_id, body):
        self.tickets[str(ticket_id)].comments.append(Comment("agent", body, "now"))

    def human_comment(self, ticket_id, body):
        self.tickets[str(ticket_id)].comments.append(Comment("human", body, "now"))

    def set_status(self, ticket_id, status):
        self.tickets[str(ticket_id)].status = status

    def mark_planned(self, ticket_id):
        self.tickets[str(ticket_id)].planned = True


class ScriptedHarness:
    """Returns canned structured outputs keyed by the call tag prefix (plan/work/review/report/fix)."""

    def __init__(self, responses: dict[str, list[dict]], on_work=None):
        self.responses = responses
        self.calls: list[tuple[str, str]] = []
        self.on_work = on_work

    def _next(self, tag: str) -> AgentResult:
        kind = tag.rsplit("-", 1)[0]
        self.calls.append((kind, tag))
        queue = self.responses.get(kind) or []
        data = queue.pop(0) if len(queue) > 1 else (queue[0] if queue else {})
        return AgentResult(ok=bool(data), data=data, cost_usd=0.1, duration_s=1.0)

    def think(self, prompt, schema, cwd, tag):
        return self._next(tag)

    def work(self, prompt, schema, cwd, tag):
        if self.on_work:
            self.on_work(tag)
        return self._next(tag)


class FakeWorkspace:
    instances: list[FakeWorkspace] = []
    checks_ok = True

    def __init__(self, cfg, repo):
        self.repo = repo
        self.path = cfg.root
        self.changed = False
        self.pushed: list[str] = []
        FakeWorkspace.instances.append(self)

    def prepare(self, branch):
        self.branch = branch

    def run_checks(self):
        return FakeWorkspace.checks_ok, "ok"

    def has_changes(self):
        return self.changed

    def git(self, *args, check=True):
        if args[:1] == ("rev-parse",):
            return self.branch
        return "1" if self.changed else "0"

    def diff_vs_base(self):
        return "+ change"

    def diffstat_vs_base(self):
        return "1 file changed"

    def changed_files(self):
        return ["app/main.py", "tests/test_main.py"]

    def commit_and_push(self, branch, message):
        self.pushed.append(message)
        return True


class FakePRs:
    merged: list[int] = []
    ci_results: list[CheckResult] = []

    def __init__(self, repo):
        self.repo = repo

    def find(self, branch):
        return None

    def open(self, branch, title, body):
        return {"number": 7, "url": "https://gh/pr/7", "state": "OPEN"}

    def comment(self, number, body):
        pass

    def wait_for_checks(self, number, timeout_s):
        return FakePRs.ci_results.pop(0) if FakePRs.ci_results else CheckResult("pass", "test=pass")

    def latest_deploy(self, workflow="deploy.yml"):
        return {"status": "completed", "conclusion": "success", "url": "https://gh/run/1"}

    def merge(self, number):
        FakePRs.merged.append(number)
