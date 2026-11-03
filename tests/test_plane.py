"""Plane adapter against an in-memory fake of Plane's REST API (routes mirror makeplane/plane api/urls)."""

import json
import re
import uuid

import httpx
import pytest
from fakes import FakeWorkspace, ScriptedHarness
from test_employee import APPROVE, PLAN, REPORT, WORK

from deleg8.employee import Employee
from deleg8.pm.plane import Plane

WS = "/api/v1/workspaces/acme"


class FakePlane:
    def __init__(self, legacy: bool = False):
        self.legacy = legacy  # older self-hosted versions only expose /issues/
        self.project = {"id": "p1", "identifier": "DEL", "name": "Website"}
        self.states = {
            s: {"id": s, "name": n, "group": g}
            for s, n, g in [
                ("s-backlog", "Backlog", "backlog"),
                ("s-todo", "Todo", "unstarted"),
                ("s-prog", "In Progress", "started"),
                ("s-done", "Done", "completed"),
            ]
        }
        self.labels: dict[str, dict] = {}
        self.items: dict[str, dict] = {}
        self.comments: dict[str, list] = {}
        self.seq = 0
        self.calls: list[str] = []

    def page(self, rows):
        return {"results": rows, "next_page_results": False, "next_cursor": None}

    def handle(self, req: httpx.Request) -> httpx.Response:
        path, m = req.url.path, req.method
        self.calls.append(f"{m} {path}")
        body = json.loads(req.content) if req.content else {}
        kind = "issues" if self.legacy else "work-items"
        if (self.legacy and "/work-items" in path) or not path.startswith(WS):
            return httpx.Response(404, json={"error": "not found"})
        rest = path[len(WS) :]
        if rest == "/projects/":
            return httpx.Response(200, json=self.page([self.project]))
        if match := re.fullmatch(rf"/{kind}/DEL-(\d+)/", rest):
            item = next((i for i in self.items.values() if i["sequence_id"] == int(match[1])), None)
            return httpx.Response(200, json=item) if item else httpx.Response(404, json={})
        rest = rest.removeprefix("/projects/p1")
        if rest == "/states/":
            if m == "POST":
                sid = f"s-{uuid.uuid4().hex[:6]}"
                self.states[sid] = {"id": sid, **body}
                return httpx.Response(201, json=self.states[sid])
            return httpx.Response(200, json=self.page(list(self.states.values())))
        if rest == "/labels/":
            if m == "POST":
                lid = f"l-{uuid.uuid4().hex[:6]}"
                self.labels[lid] = {"id": lid, **body}
                return httpx.Response(201, json=self.labels[lid])
            return httpx.Response(200, json=self.page(list(self.labels.values())))
        if rest == f"/{kind}/":
            if m == "POST":
                self.seq += 1
                iid = f"i-{uuid.uuid4().hex[:8]}"
                self.items[iid] = {"id": iid, "sequence_id": self.seq, "parent": None, "labels": [], **body}
                return httpx.Response(201, json=self.items[iid])
            return httpx.Response(200, json=self.page(list(self.items.values())))
        if match := re.fullmatch(rf"/{kind}/([\w-]+)/comments/", rest):
            if m == "POST":
                self.comments.setdefault(match[1], []).append(
                    {"comment_html": body["comment_html"], "actor": "u1", "created_at": "now"}
                )
                return httpx.Response(201, json={})
            return httpx.Response(200, json=self.page(self.comments.get(match[1], [])))
        if match := re.fullmatch(rf"/{kind}/([\w-]+)/", rest):
            item = self.items[match[1]]
            if m == "PATCH":
                item.update(body)
            return httpx.Response(200, json=item)
        return httpx.Response(404, json={"error": rest})

    def add_human_comment(self, ref: str, text: str):
        item = next(i for i in self.items.values() if f"DEL-{i['sequence_id']}" == ref)
        self.comments.setdefault(item["id"], []).append({"comment_html": f"<p>{text}</p>", "actor": "pm"})


def make_plane(fake: FakePlane) -> Plane:
    return Plane(
        base_url="https://api.plane.so",
        api_key="k",
        workspace="acme",
        project="DEL",
        transport=httpx.MockTransport(fake.handle),
    )


@pytest.mark.parametrize("legacy", [False, True])
def test_plane_ticket_lifecycle(legacy):
    fake = FakePlane(legacy=legacy)
    pm = make_plane(fake)
    pm.setup()
    assert {"In Review", "Blocked"} <= {s["name"] for s in fake.states.values()}
    assert {"deleg8", "type:epic", "deleg8:planned"} <= {lbl["name"] for lbl in fake.labels.values()}

    epic = pm.create("epic", "Changelog", "Ship a **changelog**")
    task = pm.create("task", "Page", "Do it", parent=epic.id, meta={"depends_on": [], "repo": "site"})
    assert (epic.id, task.id) == ("DEL-1", "DEL-2")
    assert task.parent == "DEL-1" and task.repo == "site" and "deleg8:meta" not in task.body
    assert "<strong>changelog</strong>" in next(iter(fake.items.values()))["description_html"]

    assert {t.id for t in pm.assigned()} == {"DEL-1", "DEL-2"}
    assert [k.id for k in pm.children("DEL-1")] == ["DEL-2"]

    pm.set_status("DEL-2", "in-review")
    assert pm.get("DEL-2").status == "in-review"
    pm.set_status("DEL-2", "done")
    assert pm.get("DEL-2").status == "done"
    assert [t.id for t in pm.assigned()] == ["DEL-1"]

    pm.mark_planned("DEL-1")
    assert pm.get("DEL-1").planned and pm.get("DEL-1").type == "epic"

    pm.comment("DEL-1", "Questions?", "🤖 **Dex** · deleg8 Junior")
    pm.set_status("DEL-1", "blocked")
    assert not pm.assigned()[0].human_replied_since_agent()
    fake.add_human_comment("DEL-1", "Here are answers")
    assert pm.assigned()[0].human_replied_since_agent()
    assert pm.ref("DEL-1") == "DEL-1" and "DEL-1" in pm.closes(pm.get("DEL-1"))
    assert pm.get("DEL-1").url == "https://app.plane.so/acme/browse/DEL-1/"
    if legacy:
        assert any("/issues/" in c for c in fake.calls)


def test_plane_rate_limit_is_retried(monkeypatch):
    fake = FakePlane()
    hits = {"n": 0}

    def handler(req):
        hits["n"] += 1
        if hits["n"] == 1:
            return httpx.Response(429, headers={"X-RateLimit-Reset": "0"})
        return fake.handle(req)

    monkeypatch.setattr("deleg8.pm.plane.time.sleep", lambda s: None)
    pm = Plane(
        base_url="http://plane.local",
        api_key="k",
        workspace="acme",
        project="DEL",
        transport=httpx.MockTransport(handler),
    )
    assert pm.project["identifier"] == "DEL"


def test_employee_runs_an_epic_end_to_end_on_plane(cfg, fakes):
    fake = FakePlane()
    pm = make_plane(fake)
    pm.setup()
    epic = pm.create("epic", "Public changelog", "Build it")

    def on_work(tag):
        for ws in FakeWorkspace.instances:
            ws.changed = True

    coder = ScriptedHarness({"work": [WORK]}, on_work=on_work)
    brain = ScriptedHarness({"plan": [PLAN], "review": [APPROVE], "report": [REPORT]})
    emp = Employee(cfg, pm=pm, coder=coder, brain=brain, journal=fakes)
    for _ in range(5):
        if not emp.run_once():
            break
    kids = pm.children(epic.id)
    assert [k.status for k in kids] == ["done", "done"]
    assert pm.get(epic.id).status == "done"
    assert FakeWorkspace.instances[-1].pushed[0].endswith(f"({kids[1].id})")  # tracker-native ref, no '#'
