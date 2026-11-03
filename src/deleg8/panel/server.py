"""deleg8 control panel: an always-on local web UI to configure projects and run/stop the AI employee.

    deleg8 panel [--port 8808]        ->  http://127.0.0.1:8808

The panel itself never starts the employee. Each project runs as the systemd user service `deleg8@<project>`,
which the panel starts/stops/pauses on request. Security: binds to localhost only, checks the Host header
(DNS-rebinding), requires a custom header on every write (forces a CORS preflight, blocking other sites), and
never returns secret values: secrets go to ~/.config/deleg8/secrets.env and configs only hold ${NAME} refs.
"""

from __future__ import annotations

import io
import json
import mimetypes
import re
import shutil
import subprocess
import sys
import threading
import time
from contextlib import redirect_stdout
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

from deleg8.secrets import mask, read_secrets, write_secrets

ROOT = Path(__file__).resolve().parents[3]
STATIC = Path(__file__).parent / "static"
PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
SECTIONS = ("employee", "pm", "repos", "knowledge", "coding_agent", "brain", "policy", "workspace")
SERVICE_ACTIONS = ("start", "stop", "restart", "enable", "disable", "pause", "resume")
_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------ helpers
def run(*cmd: str, timeout: int = 20) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(cmd, 1, "", str(e))


def cached(key: str, ttl: float, fn):
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = fn()
    with _lock:
        _cache[key] = (now, value)
    return value


def project_path(name: str) -> Path:
    if not PROJECT_RE.match(name or ""):
        raise ApiError(400, "project names use lowercase letters, digits, - and _ (max 32)")
    return ROOT / f"{name}.yaml"


def list_projects() -> list[str]:
    out = []
    for p in sorted(ROOT.glob("*.yaml")):
        if not PROJECT_RE.match(p.stem):
            continue
        try:
            raw = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError:
            continue
        if isinstance(raw, dict) and "pm" in raw and "repos" in raw:
            out.append(p.stem)
    return out


def load(name: str):
    from deleg8.config import load_config

    path = project_path(name)
    if not path.exists():
        raise ApiError(404, f"no project {name!r}")
    return load_config(path)


def unit(name: str) -> str:
    return f"deleg8@{name}.service"


def state_dir(name: str) -> Path:
    return ROOT / ".deleg8" if name == "deleg8" else ROOT / ".deleg8" / name


def service_state(name: str) -> dict:
    active = run("systemctl", "--user", "is-active", unit(name)).stdout.strip() or "unknown"
    enabled = run("systemctl", "--user", "is-enabled", unit(name)).stdout.strip() or "unknown"
    since = run("systemctl", "--user", "show", "-p", "ActiveEnterTimestamp", "--value", unit(name)).stdout.strip()
    return {"active": active, "enabled": enabled, "since": since, "paused": (state_dir(name) / "paused").exists()}


def readiness(cfg) -> dict:
    from deleg8.agents.base import make_harness

    out = {}
    for role in ("coding", "brain"):
        try:
            h = make_harness(cfg, role)
            ok, why = h.ready()
            info = h.model_info() if hasattr(h, "model_info") else {}
            out[role] = {
                "provider": h.name,
                "ok": ok,
                "detail": why,
                "model": info.get("model") or h.agent_cfg.model or "",
                "context": info.get("context_window"),
            }
        except Exception as e:
            out[role] = {"provider": "?", "ok": False, "detail": f"{type(e).__name__}: {e}", "model": ""}
    return out


def system_status() -> dict:
    import urllib.request

    def unit_active(u):
        return run("systemctl", "--user", "is-active", u).stdout.strip()

    llama = {"service": unit_active("llama-server.service"), "models": []}
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/v1/models", timeout=2) as r:
            llama["models"] = [m.get("id") for m in json.load(r).get("data", [])]
    except Exception:
        pass
    gh = cached("gh-user", 300, lambda: run("gh", "api", "user", "--jq", ".login").stdout.strip())
    return {
        "llama": llama,
        "dsh_web": unit_active("augmentor-dsh.service"),
        "github": gh or "",
        "local_ai_panel": "http://127.0.0.1:8090",
        "time": datetime.now().isoformat(timespec="seconds"),
    }


def secret_refs(obj, out=None) -> set[str]:
    out = set() if out is None else out
    if isinstance(obj, str):
        out.update(re.findall(r"\$\{([A-Z][A-Z0-9_]*)\}", obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            secret_refs(v, out)
    elif isinstance(obj, list):
        for v in obj:
            secret_refs(v, out)
    return out


# ------------------------------------------------------------------ handlers
def api_overview(_q) -> dict:
    projects = []
    for name in list_projects():
        entry = {"name": name, "service": service_state(name)}
        try:
            cfg = load(name)
            entry.update(
                {
                    "employee": cfg.employee.name,
                    "pm": cfg.pm.get("provider"),
                    "repos": [r.github for r in cfg.repos],
                    "auto_merge": cfg.policy.auto_merge,
                    "harness": cached(f"ready-{name}", 4, lambda cfg=cfg: readiness(cfg)),
                }
            )
        except Exception as e:
            entry["error"] = f"{type(e).__name__}: {e}"
        projects.append(entry)
    return {"projects": projects, "system": system_status()}


def api_config(name: str) -> dict:
    raw = yaml.safe_load(project_path(name).read_text()) or {}
    secrets = read_secrets()
    refs = sorted(secret_refs(raw))
    return {
        "name": name,
        "config": {k: raw.get(k) for k in SECTIONS if k in raw},
        "presets": sorted((raw.get("harnesses") or {}).keys()),
        "secrets": {r: {"set": r in secrets, "hint": mask(secrets[r]) if r in secrets else ""} for r in refs},
    }


def api_save_config(name: str, body: dict) -> dict:
    from deleg8.config import load_config

    path = project_path(name)
    if not path.exists():
        raise ApiError(404, f"no project {name!r}")
    new = body.get("config") or {}
    if not isinstance(new, dict):
        raise ApiError(400, "config must be an object")
    raw = yaml.safe_load(path.read_text()) or {}
    for key in SECTIONS:
        if key in new:
            raw[key] = new[key]
    raw = {k: v for k, v in raw.items() if not str(k).startswith("x-")}  # YAML anchors are resolved on load
    text = (
        "# deleg8 project config (edited in the deleg8 panel; hand edits are fine, comments are not kept)\n"
        + yaml.safe_dump(raw, sort_keys=False, allow_unicode=True, width=110)
    )
    tmp = ROOT / f".{name}.validate.yaml"
    tmp.write_text(text)
    try:
        load_config(tmp)
    except Exception as e:
        raise ApiError(400, f"config is invalid: {type(e).__name__}: {e}") from e
    finally:
        tmp.unlink(missing_ok=True)
    secrets = body.get("secrets") or {}
    if secrets:
        try:
            write_secrets({k: (v if v != "" else None) for k, v in secrets.items() if v is not None})
        except ValueError as e:
            raise ApiError(400, str(e)) from e
    backups = state_dir(name) / "config-backups"
    backups.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backups / f"{name}-{datetime.now():%Y%m%d-%H%M%S}.yaml")
    path.write_text(text)
    _cache.pop(f"ready-{name}", None)
    return {"saved": True, "restart_needed": service_state(name)["active"] == "active"}


TEMPLATE = {
    "employee": {"name": "Dex", "title": "Junior Software Engineer (AI)"},
    "pm": {"provider": "github", "github": {"repo": ""}},
    "repos": [],
    "knowledge": {"wiki_dirs": [], "databases": {}},
    "policy": {
        "auto_merge": False,
        "ai_review": True,
        "wait_for_ci": True,
        "ci_timeout_s": 1200,
        "max_fix_attempts": 2,
        "max_review_rounds": 2,
        "max_tasks_per_run": 10,
        "max_tasks_per_epic": 6,
    },
}


def api_create_project(body: dict) -> dict:
    name = (body.get("name") or "").strip().lower()
    path = project_path(name)
    if path.exists():
        raise ApiError(409, f"project {name!r} already exists")
    raw = json.loads(json.dumps(TEMPLATE))
    base = ROOT / "deleg8.yaml"
    if base.exists():  # inherit the harness setup (local model / dsh) from the main config
        main = yaml.safe_load(base.read_text()) or {}
        for key in ("coding_agent", "brain", "harnesses"):
            if key in main:
                raw[key] = main[key]
    path.write_text(
        "# deleg8 project config (created in the deleg8 panel)\n"
        + yaml.safe_dump(raw, sort_keys=False, allow_unicode=True, width=110)
    )
    return {"created": name}


def api_service(name: str, action: str) -> dict:
    if action not in SERVICE_ACTIONS:
        raise ApiError(400, f"unknown action {action!r}")
    project_path(name)
    sd = state_dir(name)
    if action == "pause":
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "paused").touch()
        return {"ok": True}
    if action == "resume":
        (sd / "paused").unlink(missing_ok=True)
        return {"ok": True}
    if not (Path.home() / ".config/systemd/user/deleg8@.service").exists():
        raise ApiError(409, "service not installed: run `dex install` once")
    if action in ("start", "enable", "stop"):  # pause only means something while Dex is running
        (sd / "paused").unlink(missing_ok=True)
        run("systemctl", "--user", "reset-failed", unit(name))
    cmd = ["systemctl", "--user", "--no-block", action, unit(name)]
    if action in ("enable", "disable"):
        cmd = ["systemctl", "--user", action, unit(name)]  # autostart only; doesn't start/stop now
    r = run(*cmd)
    if r.returncode:
        raise ApiError(500, r.stderr.strip() or f"systemctl {action} failed")
    return {"ok": True}


def api_logs(name: str, q: dict) -> dict:
    n = min(int((q.get("n") or ["200"])[0]), 2000)
    r = run("journalctl", "--user", "-u", unit(name), "-n", str(n), "-o", "short-iso", "--no-pager")
    lines = [ln for ln in r.stdout.splitlines() if not ln.startswith("-- ")]
    return {"lines": lines}


def api_activity(name: str) -> dict:
    from deleg8.journal import Journal

    db = state_dir(name) / "journal.db"
    if not db.exists():
        return {"events": [], "totals": {}}
    j = Journal(db)
    events = [
        {"ts": ts, "ticket": t, "phase": ph, "message": m, "cost": c or 0, "link": link}
        for ts, t, ph, m, c, link in j.recent(80)
    ][::-1]
    row = j.db.execute(
        "SELECT COALESCE(SUM(cost_usd),0), COALESCE(SUM(duration_s),0), COUNT(DISTINCT ticket) "
        "FROM events WHERE ticket != '-'"
    ).fetchone()
    done = j.db.execute("SELECT COUNT(*) FROM events WHERE phase IN ('done','complete')").fetchone()[0]
    return {
        "events": events,
        "totals": {"cost": row[0], "agent_minutes": row[1] / 60, "tickets": row[2], "completed": done},
    }


def api_tickets(name: str, fresh: bool) -> dict:
    from deleg8.pm.base import make_pm

    cfg = load(name)

    def fetch():
        pm = make_pm(cfg)
        return [
            {
                "id": t.id,
                "ref": pm.ref(t.id),
                "type": t.type,
                "title": t.title,
                "status": t.status,
                "url": t.url,
                "parent": t.parent,
                "planned": t.planned,
            }
            for t in pm.assigned()
        ]

    if fresh:
        _cache.pop(f"tickets-{name}", None)
    return {"tickets": cached(f"tickets-{name}", 20, fetch), "provider": cfg.pm.get("provider")}


def api_new_ticket(name: str, body: dict) -> dict:
    from deleg8.pm.base import make_pm

    title = (body.get("title") or "").strip()
    if not title:
        raise ApiError(400, "a ticket needs a title")
    kind = body.get("type") or "task"
    if kind not in ("task", "bug", "story", "epic"):
        raise ApiError(400, "type must be task, bug, story or epic")
    t = make_pm(load(name)).create(kind, title, body.get("body") or "", assign=body.get("assign", True))
    _cache.pop(f"tickets-{name}", None)
    return {"id": t.id, "url": t.url}


def api_assign(name: str, ticket: str, action: str) -> dict:
    from deleg8.pm.base import make_pm

    pm = make_pm(load(name))
    (pm.assign if action == "assign" else pm.unassign)(ticket)
    _cache.pop(f"tickets-{name}", None)
    return {"ok": True}


def api_doctor(name: str) -> dict:
    from deleg8.cli import cmd_doctor

    cfg = load(name)
    buf = io.StringIO()
    with redirect_stdout(buf):
        try:
            code = cmd_doctor(cfg, None)
        except Exception as e:
            print(f"  ✘ doctor crashed: {type(e).__name__}: {e}")
            code = 1
    return {"ok": code == 0, "output": buf.getvalue()}


def api_setup_tracker(name: str) -> dict:
    from deleg8.pm.base import make_pm

    make_pm(load(name)).setup()
    return {"ok": True}


# ------------------------------------------------------------------ http
class Handler(BaseHTTPRequestHandler):
    allowed_hosts: set[str] = set()
    server_version = "deleg8-panel"

    def log_message(self, fmt, *args):  # quiet; systemd journal gets errors only
        pass

    def send(self, code: int, body, ctype: str = "application/json") -> None:
        data = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body)).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; script-src 'self'; font-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(data)

    def host_ok(self) -> bool:
        return self.headers.get("Host", "") in self.allowed_hosts

    def body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 256 * 1024:
            raise ApiError(413, "request too large")
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except ValueError as e:
            raise ApiError(400, "body must be JSON") from e
        if not isinstance(data, dict):
            raise ApiError(400, "body must be a JSON object")
        return data

    def handle_api(self, method: str) -> None:
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p][1:]  # strip "api"
        q = parse_qs(url.query)
        try:
            if method != "GET" and self.headers.get("X-Deleg8") != "1":
                raise ApiError(403, "missing X-Deleg8 header")
            result = self.route(method, parts, q)
            self.send(200, result)
        except ApiError as e:
            self.send(e.status, {"error": str(e)})
        except Exception as e:  # never crash the panel; show the error in the UI
            self.send(500, {"error": f"{type(e).__name__}: {e}"})

    def route(self, method: str, p: list[str], q: dict):
        if method == "GET" and p == ["overview"]:
            return api_overview(q)
        if method == "POST" and p == ["projects"]:
            return api_create_project(self.body())
        if len(p) >= 2 and p[0] == "projects":
            name = p[1]
            rest = p[2:]
            if method == "GET" and rest == ["config"]:
                return api_config(name)
            if method == "PUT" and rest == ["config"]:
                return api_save_config(name, self.body())
            if method == "POST" and len(rest) == 2 and rest[0] == "service":
                return api_service(name, rest[1])
            if method == "GET" and rest == ["logs"]:
                return api_logs(name, q)
            if method == "GET" and rest == ["activity"]:
                return api_activity(name)
            if method == "GET" and rest == ["tickets"]:
                return api_tickets(name, fresh="fresh" in q)
            if method == "POST" and rest == ["tickets"]:
                return api_new_ticket(name, self.body())
            if method == "POST" and len(rest) == 3 and rest[0] == "tickets" and rest[2] in ("assign", "unassign"):
                return api_assign(name, rest[1], rest[2])
            if method == "POST" and rest == ["doctor"]:
                return api_doctor(name)
            if method == "POST" and rest == ["setup-tracker"]:
                return api_setup_tracker(name)
        raise ApiError(404, "no such endpoint")

    def do_GET(self):
        if not self.host_ok():
            return self.send(403, "forbidden", "text/plain")
        if self.path.startswith("/api/"):
            return self.handle_api("GET")
        rel = urlparse(self.path).path.lstrip("/") or "index.html"
        target = (STATIC / rel).resolve()
        if not target.is_relative_to(STATIC.resolve()) or not target.is_file():
            target = STATIC / "index.html"  # single-page app
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".woff2":
            ctype = "font/woff2"
        self.send(200, target.read_bytes(), ctype)

    def do_POST(self):
        if not self.host_ok():
            return self.send(403, "forbidden", "text/plain")
        self.handle_api("POST")

    def do_PUT(self):
        if not self.host_ok():
            return self.send(403, "forbidden", "text/plain")
        self.handle_api("PUT")


def serve(port: int = 8808, host: str = "127.0.0.1", extra_hosts: tuple[str, ...] = ()) -> None:
    Handler.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}", *extra_hosts}
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"deleg8 panel on http://127.0.0.1:{port}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)
