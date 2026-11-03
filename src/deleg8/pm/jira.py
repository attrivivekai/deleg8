"""Jira Cloud adapter (the free Jira plan works). REST API v3 + API token.

Config (deleg8.yaml):
    pm:
      provider: jira
      jira:
        base_url: https://your-site.atlassian.net
        email: you@company.com
        api_token: ${JIRA_API_TOKEN}
        project: DEL
        # optional: map deleg8 statuses -> your workflow's transition names
        transitions: {in-progress: "In Progress", in-review: "In Review", done: "Done", todo: "To Do"}

Metadata (parent/depends_on/repo) is stored in a Jira *issue property* named `deleg8`.
"""

from __future__ import annotations

import httpx

from deleg8.models import AGENT_MARKER, Comment, Ticket
from deleg8.pm.base import ASSIGN_LABEL, ProjectManager

PLANNED = "deleg8-planned"  # Jira labels can't contain ':'
TYPE_MAP = {"epic": "Epic", "story": "Story", "task": "Task", "bug": "Bug"}
FIELDS = ["summary", "description", "issuetype", "status", "labels", "comment", "parent"]


def adf_to_text(node) -> str:
    if not node:
        return ""
    if isinstance(node, str):
        return node
    if node.get("type") == "text":
        return node.get("text", "")
    sep = "\n" if node.get("type") in ("doc", "bulletList", "orderedList") else ""
    text = sep.join(adf_to_text(c) for c in node.get("content", []))
    return text + ("\n" if node.get("type") in ("paragraph", "heading", "listItem") else "")


def text_to_adf(text: str) -> dict:
    paras = [p for p in text.split("\n\n") if p.strip()]
    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": p}]} for p in paras],
    }


class Jira(ProjectManager):
    name = "jira"

    def __init__(self, base_url: str, email: str, api_token: str, project: str, transitions=None):
        self.project = project
        self.transitions = {
            "in-progress": "In Progress",
            "in-review": "In Review",
            "done": "Done",
            "todo": "To Do",
            "blocked": "Blocked",
            **(transitions or {}),
        }
        self.http = httpx.Client(base_url=base_url.rstrip("/") + "/rest/api/3", auth=(email, api_token), timeout=30)
        self._me: str | None = None

    def _req(self, method: str, path: str, **kw):
        r = self.http.request(method, path, **kw)
        r.raise_for_status()
        return r.json() if r.content else None

    @property
    def me(self) -> str:
        if self._me is None:
            self._me = self._req("GET", "/myself")["accountId"]
        return self._me

    def _to_ticket(self, d: dict) -> Ticket:
        f = d["fields"]
        labels = f.get("labels", [])
        comments = []
        for c in (f.get("comment") or {}).get("comments", []):
            body = adf_to_text(c.get("body"))
            if c.get("author", {}).get("accountId") == self.me:
                body += AGENT_MARKER
            comments.append(Comment(c.get("author", {}).get("displayName", "?"), body, c.get("created", "")))
        cat = f["status"]["statusCategory"]["key"]
        status = "done" if cat == "done" else ("in-progress" if cat == "indeterminate" else "todo")
        status = "blocked" if "deleg8-blocked" in labels else status
        props = (d.get("properties") or {}).get("deleg8") or {}
        if f.get("parent") and "parent" not in props:
            props["parent"] = f["parent"]["key"]
        type_ = next((k for k, v in TYPE_MAP.items() if v == f["issuetype"]["name"]), "task")
        return Ticket(
            id=d["key"],
            type=type_,
            title=f["summary"],
            body=adf_to_text(f.get("description")),
            status=status,
            url=f"{self.http.base_url}".replace("/rest/api/3", "") + f"/browse/{d['key']}",
            labels=labels,
            comments=comments,
            assigned=ASSIGN_LABEL in labels,
            planned=PLANNED in labels,
            stored_meta=props,
        )

    def _search(self, jql: str, limit: int = 100) -> list[Ticket]:
        data = self._req(
            "POST",
            "/search/jql",
            json={"jql": jql, "fields": FIELDS, "properties": ["deleg8"], "maxResults": limit},
        )
        return [self._to_ticket(i) for i in data.get("issues", [])]

    def assigned(self) -> list[Ticket]:
        return self._search(f'project = {self.project} AND labels = "{ASSIGN_LABEL}" AND statusCategory != Done')

    def get(self, ticket_id: str) -> Ticket:
        return self._to_ticket(
            self._req("GET", f"/issue/{ticket_id}", params={"fields": ",".join(FIELDS), "properties": "deleg8"})
        )

    def search(self, query: str, limit: int = 10) -> list[Ticket]:
        q = query.replace('"', '\\"')
        return self._search(f'project = {self.project} AND text ~ "{q}"', limit)

    def children(self, ticket_id: str) -> list[Ticket]:
        return self._search(f"project = {self.project} AND parent = {ticket_id}")

    def create(self, type, title, body, parent=None, meta=None, assign=True) -> Ticket:
        fields = {
            "project": {"key": self.project},
            "summary": title,
            "description": text_to_adf(body),
            "issuetype": {"name": TYPE_MAP.get(type, "Task")},
            "labels": [ASSIGN_LABEL] if assign else [],
        }
        if parent:
            fields["parent"] = {"key": parent}
        key = self._req("POST", "/issue", json={"fields": fields})["key"]
        meta = {**(meta or {}), **({"parent": parent} if parent else {})}
        self._req("PUT", f"/issue/{key}/properties/deleg8", json=meta)
        return self.get(key)

    def _post_comment(self, ticket_id: str, body: str) -> None:
        self._req("POST", f"/issue/{ticket_id}/comment", json={"body": text_to_adf(body.replace(AGENT_MARKER, ""))})

    def _labels(self, ticket_id: str, add=(), remove=()) -> None:
        ops = [{"add": a} for a in add] + [{"remove": r} for r in remove]
        if ops:
            self._req("PUT", f"/issue/{ticket_id}", json={"update": {"labels": ops}})

    def set_status(self, ticket_id: str, status: str) -> None:
        self._labels(
            ticket_id,
            add=["deleg8-blocked"] if status == "blocked" else [],
            remove=[] if status == "blocked" else ["deleg8-blocked"],
        )
        target = self.transitions.get(status)
        if not target:
            return
        for t in self._req("GET", f"/issue/{ticket_id}/transitions")["transitions"]:
            if t["name"].lower() == target.lower() or t["to"]["name"].lower() == target.lower():
                self._req("POST", f"/issue/{ticket_id}/transitions", json={"transition": {"id": t["id"]}})
                return

    def assign(self, ticket_id: str) -> None:
        self._labels(ticket_id, add=[ASSIGN_LABEL])

    def unassign(self, ticket_id: str) -> None:
        self._labels(ticket_id, remove=[ASSIGN_LABEL])

    def mark_planned(self, ticket_id: str) -> None:
        self._labels(ticket_id, add=[PLANNED])
