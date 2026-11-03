"""The interface every project-management adapter implements."""

from __future__ import annotations

from abc import ABC, abstractmethod

from deleg8.models import AGENT_MARKER, Ticket

ASSIGN_LABEL = "deleg8"
PLANNED_LABEL = "deleg8:planned"


class ProjectManager(ABC):
    name = "base"

    @abstractmethod
    def assigned(self) -> list[Ticket]:
        """Open tickets assigned to the AI employee."""

    @abstractmethod
    def get(self, ticket_id: str) -> Ticket: ...

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> list[Ticket]: ...

    @abstractmethod
    def create(
        self,
        type: str,
        title: str,
        body: str,
        parent: str | None = None,
        meta: dict | None = None,
        assign: bool = True,
    ) -> Ticket: ...

    @abstractmethod
    def children(self, ticket_id: str) -> list[Ticket]: ...

    @abstractmethod
    def _post_comment(self, ticket_id: str, body: str) -> None: ...

    @abstractmethod
    def set_status(self, ticket_id: str, status: str) -> None: ...

    @abstractmethod
    def mark_planned(self, ticket_id: str) -> None: ...

    def ref(self, ticket_id: str) -> str:
        """How to refer to a ticket in commits, PRs and comments."""
        return str(ticket_id)

    def closes(self, ticket: Ticket) -> str:
        """PR-body line linking the ticket (GitHub uses `Closes #N` to auto-close)."""
        return f"Ticket: [{ticket.id}]({ticket.url})"

    def setup(self) -> None:  # noqa: B027 - optional hook
        """Create labels/fields the harness relies on (idempotent)."""

    def comment(self, ticket_id: str, body: str, signature: str = "") -> None:
        sig = f"\n\n---\n{signature}" if signature else ""
        self._post_comment(ticket_id, f"{body.strip()}{sig}\n{AGENT_MARKER}")


def make_pm(cfg) -> ProjectManager:
    provider = cfg.pm.get("provider", "github")
    if provider == "github":
        from deleg8.pm.github import GitHubIssues

        return GitHubIssues(**cfg.pm.get("github", {}))
    if provider == "plane":
        from deleg8.pm.plane import Plane

        return Plane(**cfg.pm.get("plane", {}))
    if provider == "jira":
        from deleg8.pm.jira import Jira

        return Jira(**cfg.pm.get("jira", {}))
    raise ValueError(f"unknown PM provider {provider!r}")
