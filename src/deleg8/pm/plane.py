"""Plane (https://plane.so) adapter: an open-source (AGPL-3.0), Jira-like project tracker.

Free options: self-hosted Community Edition (Docker, no user limit) or Plane Cloud's free tier.

Config (deleg8.yaml):
    pm:
      provider: plane
      plane:
        base_url: https://api.plane.so        # or your self-hosted URL, e.g. http://localhost
        api_key: ${PLANE_API_KEY}             # Profile settings -> Personal access tokens
        workspace: deleg8                     # workspace slug from the URL
        project: DEL                          # project identifier (or project UUID)

Mapping (endpoints verified against makeplane/plane apps/api/plane/api/urls/work_item.py):
    ticket id   -> "<PROJECT>-<sequence>"  e.g. DEL-12
    type        -> label `type:<epic|story|task|bug>`  (epics are a paid Plane feature; labels work everywhere)
    status      -> Plane *states* (Todo / In Progress / In Review / Blocked / Done), created by `setup()`
    hierarchy   -> native `parent` field (sub-work-items)
    depends_on  -> `deleg8:meta {...}` line in the description
"""

from __future__ import annotations

import html
import json
import re
import time

import httpx
import markdown as md

from deleg8.models import AGENT_MARKER, META_RE, STATUSES, Comment, Ticket
from deleg8.pm.base import ASSIGN_LABEL, PLANNED_LABEL, ProjectManager

STATE_DEFAULTS = {  # deleg8 status -> (Plane state name, state group, color)
    "todo": ("Todo", "unstarted", "#9aa3b5"),
    "in-progress": ("In Progress", "started", "#f59e0b"),
    "in-review": ("In Review", "started", "#3b82f6"),
    "blocked": ("Blocked", "started", "#dc2626"),
    "done": ("Done", "completed", "#16a34a"),
}
LABEL_COLORS = {
    ASSIGN_LABEL: "#7c5cff",
    PLANNED_LABEL: "#c5b8ff",
    "type:epic": "#3e1f8f",
    "type:story": "#1d76db",
    "type:task": "#0e8a16",
    "type:bug": "#d73a4a",
}
META_LINE_RE = re.compile(r"deleg8:meta (\{.*?\})", re.S)


def html_to_text(value: str) -> str:
    text = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>|</pre>", "\n", value or "", flags=re.I)
    text = re.sub(r"<li[^>]*>", "- ", text, flags=re.I)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def _parent_id(item: dict) -> str | None:
    parent = item.get("parent")
    return parent.get("id") if isinstance(parent, dict) else parent


def to_html(markdown_text: str) -> str:
    return md.markdown(markdown_text, extensions=["fenced_code", "tables", "sane_lists"])


class Plane(ProjectManager):
    name = "plane"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        workspace: str,
        project: str,
        states: dict[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.http = httpx.Client(
            base_url=f"{self.base_url}/api/v1/workspaces/{workspace}",
            headers={"X-API-Key": api_key},
            timeout=30,
            transport=transport,
        )
        self.workspace = workspace
        self.web_url = self.base_url.replace("://api.plane.so", "://app.plane.so")  # cloud API vs web hosts
        self._project_ref = project
        self._project: dict | None = None
        self.state_names = {k: (states or {}).get(k, v[0]) for k, v in STATE_DEFAULTS.items()}
        self._labels: dict[str, str] | None = None  # name -> id
        self._states: dict[str, dict] | None = None  # id -> state
        self._items = "work-items"  # falls back to legacy "issues" on older self-hosted versions

    # ----------------------------------------------------------------- http
    def _req(self, method: str, path: str, **kw):
        for _attempt in range(5):
            r = self.http.request(method, path, **kw)
            if r.status_code == 429:  # 60 req/min per key: wait for the window to reset
                reset = float(r.headers.get("X-RateLimit-Reset", time.time() + 10))
                time.sleep(min(max(reset - time.time(), 1), 60))
                continue
            if r.status_code == 404 and self._items == "work-items" and "/work-items" in path:
                legacy = self.http.request(method, path.replace("/work-items", "/issues"), **kw)
                if legacy.status_code != 404:  # older self-hosted Plane: only the /issues/ routes exist
                    self._items = "issues"
                    legacy.raise_for_status()
                    return legacy.json() if legacy.content else None
            r.raise_for_status()
            return r.json() if r.content else None
        raise RuntimeError(f"Plane API rate limit: gave up on {method} {path}")

    def _paginate(self, path: str, params: dict | None = None) -> list[dict]:
        out, cursor = [], None
        while True:
            q = {"per_page": 100, **(params or {}), **({"cursor": cursor} if cursor else {})}
            page = self._req("GET", path, params=q)
            if isinstance(page, list):
                return out + page
            out += page.get("results", [])
            if not page.get("next_page_results"):
                return out
            cursor = page.get("next_cursor")

    @property
    def project(self) -> dict:
        if self._project is None:
            projects = self._paginate("/projects/")
            match = [p for p in projects if self._project_ref in (p.get("identifier"), p.get("id"))]
            if not match:
                raise KeyError(f"Plane project {self._project_ref!r} not found in workspace {self.workspace!r}")
            self._project = match[0]
        return self._project

    def _p(self, suffix: str = "") -> str:
        return f"/projects/{self.project['id']}{suffix}"

    def _items_path(self, item_id: str = "") -> str:
        return self._p(f"/{self._items}/" + (f"{item_id}/" if item_id else ""))

    # ------------------------------------------------------- labels / states
    @property
    def labels(self) -> dict[str, str]:
        if self._labels is None:
            self._labels = {lbl["name"]: lbl["id"] for lbl in self._paginate(self._p("/labels/"))}
        return self._labels

    @property
    def states(self) -> dict[str, dict]:
        if self._states is None:
            self._states = {s["id"]: s for s in self._paginate(self._p("/states/"))}
        return self._states

    def _state_id(self, status: str) -> str:
        name = self.state_names[status]
        for sid, s in self.states.items():
            if s["name"].lower() == name.lower():
                return sid
        group = STATE_DEFAULTS[status][1]  # fall back to any state in the right group
        for sid, s in self.states.items():
            if s.get("group") == group:
                return sid
        raise KeyError(f"no Plane state for {status!r}; run `deleg8 bootstrap` or create state {name!r}")

    def _label_id(self, name: str) -> str:
        if name not in self.labels:
            created = self._req(
                "POST", self._p("/labels/"), json={"name": name, "color": LABEL_COLORS.get(name, "#9aa3b5")}
            )
            self.labels[name] = created["id"]
        return self.labels[name]

    def setup(self) -> None:
        for name in LABEL_COLORS:
            self._label_id(name)
        existing = {s["name"].lower() for s in self.states.values()}
        for status, (_, group, color) in STATE_DEFAULTS.items():
            name = self.state_names[status]
            if name.lower() not in existing:
                self._req("POST", self._p("/states/"), json={"name": name, "group": group, "color": color})
        self._states = None

    # ---------------------------------------------------------------- mapping
    def _ref_of(self, item: dict) -> str:
        return f"{self.project['identifier']}-{item['sequence_id']}"

    def _to_ticket(
        self, item: dict, comments: list[Comment] | None = None, by_uuid: dict[str, dict] | None = None
    ) -> Ticket:
        label_ids = [lbl["id"] if isinstance(lbl, dict) else lbl for lbl in item.get("labels") or []]
        id_to_name = {v: k for k, v in self.labels.items()}
        labels = [id_to_name.get(i, i) for i in label_ids]
        state = item.get("state")
        state = state if isinstance(state, dict) else self.states.get(state, {})
        if state.get("group") in ("completed", "cancelled"):
            status = "done"
        else:
            by_name = {v.lower(): k for k, v in self.state_names.items()}
            status = by_name.get((state.get("name") or "").lower(), "todo")
        desc_text = html_to_text(item.get("description_html") or "")
        meta_match = META_LINE_RE.search(desc_text)
        meta = json.loads(meta_match.group(1)) if meta_match else {}
        body = META_LINE_RE.sub("", desc_text).strip()
        parent = _parent_id(item)
        if parent:
            pitem = (by_uuid or {}).get(parent) or self._req("GET", self._items_path(parent))
            meta["parent"] = self._ref_of(pitem)
        return Ticket(
            id=self._ref_of(item),
            type=next((lbl.split(":", 1)[1] for lbl in labels if lbl.startswith("type:")), "task"),
            title=item["name"],
            body=body,
            status=status,
            url=f"{self.web_url}/{self.workspace}/browse/{self._ref_of(item)}/",
            labels=labels,
            comments=comments or [],
            assigned=ASSIGN_LABEL in labels,
            planned=PLANNED_LABEL in labels,
            stored_meta=meta,
        )

    def _comments(self, item_id: str) -> list[Comment]:
        out = []
        for c in self._paginate(self._items_path(item_id) + "comments/"):
            body = html_to_text(c.get("comment_html") or "")
            if "deleg8:agent" in (c.get("comment_html") or "") or " · deleg8 " in body:
                body += AGENT_MARKER
            out.append(Comment(str(c.get("actor") or c.get("created_by") or "?"), body, c.get("created_at", "")))
        return out

    def _all(self) -> list[dict]:
        return self._paginate(self._items_path())

    def _uuid(self, ticket_id: str) -> str:
        seq = str(ticket_id).rsplit("-", 1)[-1]
        item = self._req("GET", f"/{self._items}/{self.project['identifier']}-{seq}/")
        return item["id"]

    # ------------------------------------------------------------------ reads
    def assigned(self) -> list[Ticket]:
        items = self._all()
        by_uuid = {i["id"]: i for i in items}
        tickets = []
        for item in items:
            t = self._to_ticket(item, by_uuid=by_uuid)
            if t.assigned and t.status != "done":
                if t.status == "blocked":  # only blocked tickets need the discussion here (did a human reply?)
                    t.comments = self._comments(item["id"])
                tickets.append(t)
        return tickets

    def get(self, ticket_id: str) -> Ticket:
        seq = str(ticket_id).rsplit("-", 1)[-1]
        item = self._req("GET", f"/{self._items}/{self.project['identifier']}-{seq}/")
        return self._to_ticket(item, comments=self._comments(item["id"]))

    def search(self, query: str, limit: int = 10) -> list[Ticket]:
        items = self._all()
        by_uuid = {i["id"]: i for i in items}
        q = query.lower().strip()
        hits = [
            i
            for i in items
            if not q or q in i["name"].lower() or q in html_to_text(i.get("description_html") or "").lower()
        ]
        return [self._to_ticket(i, by_uuid=by_uuid) for i in hits[:limit]]

    def children(self, ticket_id: str) -> list[Ticket]:
        items = self._all()
        by_uuid = {i["id"]: i for i in items}
        parent = self._uuid(ticket_id)
        return [self._to_ticket(i, by_uuid=by_uuid) for i in items if _parent_id(i) == parent]

    # ----------------------------------------------------------------- writes
    def create(self, type, title, body, parent=None, meta=None, assign=True) -> Ticket:
        meta = {k: v for k, v in (meta or {}).items() if k != "parent"}
        text = META_RE.sub("", body).strip()
        if meta:
            text += f"\n\n`deleg8:meta {json.dumps(meta)}`"
        labels = [f"type:{type}"] + ([ASSIGN_LABEL] if assign else [])
        payload = {
            "name": title,
            "description_html": to_html(text),
            "labels": [self._label_id(lbl) for lbl in labels],
            "state": self._state_id("todo"),
        }
        if parent:
            payload["parent"] = self._uuid(parent)
        item = self._req("POST", self._items_path(), json=payload)
        return self._to_ticket(item)

    def _post_comment(self, ticket_id: str, body: str) -> None:
        html_body = to_html(body.replace(AGENT_MARKER, "")) + "<p><sub>deleg8:agent</sub></p>"
        self._req("POST", self._items_path(self._uuid(ticket_id)) + "comments/", json={"comment_html": html_body})

    def set_status(self, ticket_id: str, status: str) -> None:
        assert status in STATUSES, status
        self._req("PATCH", self._items_path(self._uuid(ticket_id)), json={"state": self._state_id(status)})

    def mark_planned(self, ticket_id: str) -> None:
        uuid = self._uuid(ticket_id)
        item = self._req("GET", self._items_path(uuid))
        current = [lbl["id"] if isinstance(lbl, dict) else lbl for lbl in item.get("labels") or []]
        self._req("PATCH", self._items_path(uuid), json={"labels": [*current, self._label_id(PLANNED_LABEL)]})

    def ref(self, ticket_id: str) -> str:
        return str(ticket_id)
