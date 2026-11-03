"""GitHub Issues as the project-management tool (free, and sits right next to the code).

Mapping:  type  -> label `type:<epic|story|task|bug>`
          status-> label `status:<...>`, closed issue = done
          hierarchy -> GitHub sub-issues + a hidden metadata block in the body
"""

from __future__ import annotations

from deleg8.models import STATUSES, Comment, Ticket, with_meta
from deleg8.pm.base import ASSIGN_LABEL, PLANNED_LABEL, ProjectManager
from deleg8.shell import CommandError, gh_json, run

FIELDS = "number,title,body,labels,url,comments,state"

LABELS = {
    ASSIGN_LABEL: ("7c5cff", "Assigned to the deleg8 AI employee"),
    PLANNED_LABEL: ("c5b8ff", "AI employee has broken this down into tasks"),
    "type:epic": ("3e1f8f", "Epic"),
    "type:story": ("1d76db", "Story"),
    "type:task": ("0e8a16", "Task"),
    "type:bug": ("d73a4a", "Bug"),
    "status:todo": ("ededed", "Ready to start"),
    "status:in-progress": ("fbca04", "Being worked on"),
    "status:in-review": ("0075ca", "PR open, in review / CI"),
    "status:blocked": ("b60205", "Needs human input"),
}


class GitHubIssues(ProjectManager):
    name = "github"

    def __init__(self, repo: str):
        self.repo = repo

    # ------------------------------------------------------------- mapping
    def _to_ticket(self, d: dict) -> Ticket:
        labels = [lbl["name"] for lbl in d.get("labels", [])]
        type_ = next((lbl.split(":", 1)[1] for lbl in labels if lbl.startswith("type:")), "task")
        status = "done" if d.get("state", "OPEN").upper() == "CLOSED" else "todo"
        for lbl in labels:
            if lbl.startswith("status:"):
                status = status if status == "done" else lbl.split(":", 1)[1]
        comments = [
            Comment(
                author=(c.get("author") or {}).get("login", "?"),
                body=c.get("body", ""),
                created_at=c.get("createdAt", ""),
            )
            for c in d.get("comments", [])
        ]
        return Ticket(
            id=str(d["number"]),
            type=type_,
            title=d["title"],
            body=d.get("body") or "",
            status=status,
            url=d["url"],
            labels=labels,
            comments=comments,
            assigned=ASSIGN_LABEL in labels,
            planned=PLANNED_LABEL in labels,
        )

    def _list(self, *args: str) -> list[Ticket]:
        data = gh_json(["issue", "list", "-R", self.repo, "--limit", "200", "--json", FIELDS, *args])
        return [self._to_ticket(d) for d in data or []]

    def ref(self, ticket_id: str) -> str:
        return f"#{ticket_id}"

    def closes(self, ticket: Ticket) -> str:
        return f"Closes #{ticket.id}"

    # ------------------------------------------------------------- reads
    def assigned(self) -> list[Ticket]:
        return self._list("--label", ASSIGN_LABEL, "--state", "open")

    def get(self, ticket_id: str) -> Ticket:
        return self._to_ticket(
            gh_json(["issue", "view", str(ticket_id).lstrip("#"), "-R", self.repo, "--json", FIELDS])
        )

    def search(self, query: str, limit: int = 10) -> list[Ticket]:
        extra = ["--search", query] if query.strip() else []
        return self._list(*extra, "--state", "all")[:limit]

    def children(self, ticket_id: str) -> list[Ticket]:
        return [t for t in self._list("--state", "all", "--label", ASSIGN_LABEL) if t.parent == str(ticket_id)]

    # ------------------------------------------------------------- writes
    def setup(self) -> None:
        for name, (color, desc) in LABELS.items():
            run(
                [
                    "gh",
                    "label",
                    "create",
                    name,
                    "-R",
                    self.repo,
                    "--color",
                    color,
                    "--description",
                    desc,
                    "--force",
                ]
            )

    def create(self, type, title, body, parent=None, meta=None, assign=True) -> Ticket:
        meta = dict(meta or {})
        if parent:
            meta["parent"] = str(parent)
        labels = [f"type:{type}", "status:todo"] + ([ASSIGN_LABEL] if assign else [])
        args = ["issue", "create", "-R", self.repo, "--title", title, "--body-file", "-"]
        for lbl in labels:
            args += ["--label", lbl]
        url = run(["gh", *args], input=with_meta(body, meta) if meta else body).stdout.strip()
        number = url.rstrip("/").rsplit("/", 1)[-1]
        if parent:
            self._link_sub_issue(str(parent), number)
        return self.get(number)

    def _link_sub_issue(self, parent: str, child: str) -> None:
        try:
            child_id = gh_json(["api", f"repos/{self.repo}/issues/{child}"])["id"]
            run(
                [
                    "gh",
                    "api",
                    "-X",
                    "POST",
                    f"repos/{self.repo}/issues/{parent}/sub_issues",
                    "-F",
                    f"sub_issue_id={child_id}",
                ]
            )
        except CommandError:
            pass  # sub-issues not available: the metadata block still records the parent

    def _post_comment(self, ticket_id: str, body: str) -> None:
        run(["gh", "issue", "comment", str(ticket_id), "-R", self.repo, "--body-file", "-"], input=body)

    def _edit_labels(self, ticket_id: str, add: list[str], remove: list[str]) -> None:
        args = ["gh", "issue", "edit", str(ticket_id), "-R", self.repo]
        for lbl in add:
            args += ["--add-label", lbl]
        for lbl in remove:
            args += ["--remove-label", lbl]
        if add or remove:
            run(args)

    def set_status(self, ticket_id: str, status: str) -> None:
        assert status in STATUSES, status
        current = self.get(ticket_id)
        stale = [lbl for lbl in current.labels if lbl.startswith("status:") and lbl != f"status:{status}"]
        if status == "done":
            self._edit_labels(ticket_id, [], stale)
            if current.status != "done":
                run(["gh", "issue", "close", str(ticket_id), "-R", self.repo, "--reason", "completed"])
            return
        if current.status == "done":
            run(["gh", "issue", "reopen", str(ticket_id), "-R", self.repo])
        add = [] if f"status:{status}" in current.labels else [f"status:{status}"]
        self._edit_labels(ticket_id, add, stale)

    def assign(self, ticket_id: str) -> None:
        t = self.get(ticket_id)
        self._edit_labels(
            ticket_id, [ASSIGN_LABEL] + ([] if any(x.startswith("status:") for x in t.labels) else ["status:todo"]), []
        )

    def unassign(self, ticket_id: str) -> None:
        self._edit_labels(ticket_id, [], [ASSIGN_LABEL])

    def mark_planned(self, ticket_id: str) -> None:
        self._edit_labels(ticket_id, [PLANNED_LABEL], [])
