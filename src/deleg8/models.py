"""Tool-agnostic ticket model shared by every PM adapter."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

AGENT_MARKER = "<!-- deleg8:agent -->"
META_RE = re.compile(r"<!-- deleg8:meta (\{.*?\}) -->", re.S)

TYPES = ("epic", "story", "task", "bug")
STATUSES = ("todo", "in-progress", "in-review", "blocked", "done")


@dataclass
class Comment:
    author: str
    body: str
    created_at: str

    @property
    def by_agent(self) -> bool:
        return AGENT_MARKER in self.body


@dataclass
class Ticket:
    id: str  # PM-native key: "12" for GitHub, "DEL-12" for Jira
    type: str
    title: str
    body: str
    status: str
    url: str
    labels: list[str] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)
    assigned: bool = False
    planned: bool = False
    stored_meta: dict[str, Any] | None = None  # adapters that store metadata out-of-band (Jira)

    @property
    def meta(self) -> dict[str, Any]:
        if self.stored_meta is not None:
            return self.stored_meta
        m = META_RE.search(self.body or "")
        return json.loads(m.group(1)) if m else {}

    @property
    def parent(self) -> str | None:
        p = self.meta.get("parent")
        return str(p) if p else None

    @property
    def depends_on(self) -> list[str]:
        return [str(d) for d in self.meta.get("depends_on", [])]

    @property
    def repo(self) -> str | None:
        return self.meta.get("repo")

    @property
    def is_container(self) -> bool:
        return self.type in ("epic", "story")

    def human_replied_since_agent(self) -> bool:
        """True if the latest comment is from a human and follows an agent comment."""
        if not self.comments:
            return False
        last_agent = max((i for i, c in enumerate(self.comments) if c.by_agent), default=-1)
        return any(not c.by_agent for c in self.comments[last_agent + 1 :]) and last_agent >= 0

    def context_markdown(self, max_comments: int = 15) -> str:
        body = META_RE.sub("", self.body or "").strip()
        out = [
            f"# [{self.type}] {self.title} ({self.id})",
            f"URL: {self.url}",
            "",
            body or "_(no description)_",
        ]
        if self.comments:
            out += ["", "## Discussion"]
            for c in self.comments[-max_comments:]:
                who = "AI employee (you)" if c.by_agent else c.author
                out += [f"**{who}** ({c.created_at}):", c.body.replace(AGENT_MARKER, "").strip(), ""]
        return "\n".join(out)


def with_meta(body: str, meta: dict[str, Any]) -> str:
    body = META_RE.sub("", body).rstrip()
    return f"{body}\n\n<!-- deleg8:meta {json.dumps(meta)} -->"
