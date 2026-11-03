"""deleg8 panel API: config round-trip, secrets handling and request hardening (no systemd needed)."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
import yaml

from deleg8.panel import server
from deleg8.secrets import read_secrets


@pytest.fixture()
def panel(tmp_path, monkeypatch, cfg):
    root = tmp_path / "panelroot"
    root.mkdir()
    (root / "deleg8.yaml").write_text(cfg.path.read_text())
    monkeypatch.setattr(server, "ROOT", root)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = srv.server_address[1]
    server.Handler.allowed_hosts = {f"127.0.0.1:{port}"}
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def call(method, path, body=None, headers=None, host=None):
        h = {"X-Deleg8": "1", "Content-Type": "application/json", **(headers or {})}
        if host:
            h["Host"] = host
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            method=method,
            headers=h,
            data=json.dumps(body).encode() if body is not None else None,
        )
        try:
            with urllib.request.urlopen(req) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if r.headers["Content-Type"] == "application/json" else raw)
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    yield call, root
    srv.shutdown()


def test_rejects_foreign_host_and_missing_write_header(panel):
    call, _ = panel
    assert call("GET", "/api/projects/deleg8/config", host="evil.example")[0] == 403
    assert call("POST", "/api/projects", {"name": "x"}, headers={"X-Deleg8": ""})[0] == 403


def test_static_paths_cannot_escape(panel):
    call, _ = panel
    status, body = call("GET", "/../../deleg8.yaml")
    assert status == 200 and b"<!doctype html>" in body.lower()


def test_project_names_are_validated(panel):
    call, _ = panel
    assert call("POST", "/api/projects", {"name": "../etc"})[0] == 400
    assert call("GET", "/api/projects/Bad%20Name/config")[0] == 400


def test_create_configure_and_secret_roundtrip(panel):
    call, root = panel
    assert call("POST", "/api/projects", {"name": "acme"})[0] == 200
    assert call("POST", "/api/projects", {"name": "acme"})[0] == 409
    status, cfg = call("GET", "/api/projects/acme/config")
    assert status == 200 and cfg["config"]["policy"]["auto_merge"] is False
    conf = cfg["config"]
    conf["pm"] = {
        "provider": "jira",
        "jira": {
            "base_url": "https://a.atlassian.net",
            "email": "a@b.c",
            "project": "AC",
            "api_token": "${ACME_JIRA_API_TOKEN}",
        },
    }
    conf["repos"] = [{"name": "api", "github": "acme/api", "checks": ["npm test"]}]
    status, res = call(
        "PUT", "/api/projects/acme/config", {"config": conf, "secrets": {"ACME_JIRA_API_TOKEN": "tok-supersecret-9876"}}
    )
    assert status == 200 and res["saved"]
    text = (root / "acme.yaml").read_text()
    assert "tok-supersecret-9876" not in text and "${ACME_JIRA_API_TOKEN}" in text
    assert read_secrets()["ACME_JIRA_API_TOKEN"] == "tok-supersecret-9876"
    _, cfg = call("GET", "/api/projects/acme/config")
    assert cfg["secrets"]["ACME_JIRA_API_TOKEN"] == {"set": True, "hint": "••••••9876"}
    assert "supersecret" not in json.dumps(cfg)
    assert list((root / ".deleg8" / "acme" / "config-backups").iterdir())


def test_invalid_config_is_rejected_and_file_untouched(panel):
    call, root = panel
    before = (root / "deleg8.yaml").read_text()
    status, body = call("PUT", "/api/projects/deleg8/config", {"config": {"coding_agent": {"bogus_field": 1}}})
    assert status == 400 and b"invalid" in body
    assert (root / "deleg8.yaml").read_text() == before


def test_pause_resume_without_systemd(panel):
    call, root = panel
    assert call("POST", "/api/projects/deleg8/service/pause")[0] == 200
    assert (root / ".deleg8" / "paused").exists()
    assert call("POST", "/api/projects/deleg8/service/resume")[0] == 200
    assert not (root / ".deleg8" / "paused").exists()
    assert call("POST", "/api/projects/deleg8/service/explode")[0] == 400


def test_saved_config_keeps_unmanaged_sections(panel):
    call, root = panel
    raw = yaml.safe_load((root / "deleg8.yaml").read_text())
    raw["harnesses"] = {"claude": {"coding_agent": {"provider": "claude_code"}}}
    (root / "deleg8.yaml").write_text(yaml.safe_dump(raw))
    _, cfg = call("GET", "/api/projects/deleg8/config")
    cfg["config"]["employee"] = {"name": "Nova"}
    assert call("PUT", "/api/projects/deleg8/config", {"config": cfg["config"]})[0] == 200
    saved = yaml.safe_load((root / "deleg8.yaml").read_text())
    assert saved["employee"]["name"] == "Nova" and "claude" in saved["harnesses"]
