"""deleg8 command line.

deleg8 doctor                  check that every tool the employee needs is reachable
deleg8 bootstrap               create the demo company: website repo, CI/CD, labels, Pages, DB, warehouse
deleg8 seed                    create the seed backlog in the PM tool
deleg8 run                     one pass over the backlog
deleg8 work [--interval 60]    keep working (daemon)
deleg8 status                  board + recent journal
deleg8 tool <name> [args]      research tools (wiki-search, db-query, ...) for shell-based harnesses
"""

from __future__ import annotations

import argparse
import fcntl
import shutil
import sys
import tempfile
import time
from pathlib import Path

import yaml

from deleg8.config import Config, load_config
from deleg8.shell import CommandError, run

ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- helpers
def ok(msg: str) -> None:
    print(f"  ✔ {msg}")


def bad(msg: str) -> None:
    print(f"  ✘ {msg}")


def lock(cfg: Config):
    fh = open(cfg.state_dir / "lock", "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit("another deleg8 run is in progress (.deleg8/lock)")
    return fh


# ---------------------------------------------------------------- commands
def cmd_doctor(cfg: Config, _args) -> int:
    from deleg8.tools import Tools

    failures = 0
    print("deleg8 doctor")
    for binary in ["git", "gh", cfg.coding_agent.provider.replace("claude_code", "claude")]:
        (ok if shutil.which(binary) else bad)(f"{binary} on PATH")
        failures += not shutil.which(binary)
    try:
        who = run(["gh", "api", "user", "--jq", ".login"]).stdout.strip()
        ok(f"GitHub API authenticated as {who}")
    except Exception as e:
        bad(f"GitHub API: {e}".splitlines()[0])
        failures += 1
    p = run(["ssh", "-T", "-o", "BatchMode=yes", "git@github.com"], check=False, timeout=20)
    (ok if "successfully authenticated" in p.stderr else bad)("git over SSH to github.com")
    tools = Tools(cfg)
    for name in cfg.databases:
        try:
            tools.db_query(name, "SELECT 1 AS ok")
            ok(f"database '{name}' reachable (read-only)")
        except Exception as e:
            bad(f"database '{name}': {str(e).splitlines()[0][:120]}")
            failures += 1
    pages = sum(1 for d in cfg.wiki_dirs for _ in d.rglob("*.md"))
    (ok if pages else bad)(f"wiki: {pages} pages in {[str(d) for d in cfg.wiki_dirs]}")
    for r in cfg.repos:
        p = run(["gh", "repo", "view", r.github, "--json", "name"], check=False)
        (ok if p.returncode == 0 else bad)(f"repo {r.github}")
        failures += p.returncode != 0
    try:
        from deleg8.pm.base import make_pm

        n = len(make_pm(cfg).assigned())
        ok(f"PM tool ({cfg.pm.get('provider')}): {n} open tickets assigned to {cfg.employee.name}")
    except Exception as e:
        bad(f"PM tool: {str(e).splitlines()[0][:160]}")
        failures += 1
    return 1 if failures else 0


def cmd_bootstrap(cfg: Config, args) -> int:
    from deleg8.pm.base import make_pm

    template = ROOT / "demo" / "website"
    repo = cfg.repos[0]
    owner, name = repo.github.split("/")
    print(f"bootstrapping demo company -> {repo.github}")

    if run(["gh", "repo", "view", repo.github], check=False).returncode != 0:
        run(
            [
                "gh",
                "repo",
                "create",
                repo.github,
                f"--{args.visibility}",
                "--description",
                "deleg8 marketing site: the workplace of deleg8's AI junior engineer",
                "--homepage",
                repo.deploy_url or "",
            ]
        )
        ok(f"created repo {repo.github}")
    else:
        ok(f"repo {repo.github} exists")

    has_main = run(["git", "ls-remote", "--heads", repo.clone_url, repo.default_branch], check=False).stdout
    if not has_main.strip():
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / name
            shutil.copytree(
                template,
                dst,
                symlinks=True,
                ignore=shutil.ignore_patterns(".venv", "__pycache__", "dist", "*.db", ".ruff_cache", ".pytest_cache"),
            )
            for cmd in (
                ["git", "init", "-q", "-b", repo.default_branch],
                ["git", "add", "-A"],
                ["git", "commit", "-qm", "chore: initial deleg8 website"],
                ["git", "push", "-q", repo.clone_url, repo.default_branch],
            ):
                run(cmd, cwd=dst)
        ok("pushed website template")
    else:
        ok("website already has code")

    p = run(["gh", "api", "-X", "POST", f"repos/{repo.github}/pages", "-f", "build_type=workflow"], check=False)
    ok(
        "GitHub Pages enabled (workflow)"
        if p.returncode == 0 or "already" in p.stderr.lower()
        else f"GitHub Pages: {p.stderr.strip()[:120]}"
    )
    make_pm(cfg).setup()
    ok("PM labels created")

    sys.path.insert(0, str(ROOT / "demo" / "warehouse"))
    from build_warehouse import build  # type: ignore

    wh = cfg.databases.get("warehouse", {}).get("url", "").removeprefix("duckdb:///")
    if wh:
        build(Path(wh))
        ok(f"warehouse built: {wh}")
    if not args.skip_infra:
        run(
            [
                "docker",
                "compose",
                "-f",
                str(ROOT / "demo" / "infra" / "docker-compose.yml"),
                "up",
                "-d",
                "--wait",
            ],
            timeout=300,
        )
        ok("production database up (postgres on :5434)")
    return 0


def cmd_seed(cfg: Config, args) -> int:
    from deleg8.pm.base import make_pm

    pm = make_pm(cfg)
    data = yaml.safe_load(Path(args.file).read_text())
    existing = {t.title for t in pm.search("", limit=500)}
    for spec in data["tickets"]:
        if args.only and spec["key"] not in args.only:
            continue
        if spec["title"] in existing:
            ok(f"exists: {spec['title']}")
            continue
        t = pm.create(spec["type"], spec["title"], spec["body"], assign=spec.get("assign", True))
        ok(f"created #{t.id} [{spec['type']}] {spec['title']} -> {t.url}")
    return 0


def cmd_run(cfg: Config, args) -> int:
    from deleg8.employee import Employee

    _lock = lock(cfg)
    emp = Employee(cfg)
    if args.ticket:  # work a single ticket now, regardless of the queue
        t = emp.pm.get(args.ticket)
        emp._guard(t, emp.plan if t.is_container else emp.execute)
        return 0
    n = emp.run_once()
    print(f"pass complete: {n} action(s)")
    return 0


def cmd_work(cfg: Config, args) -> int:
    from deleg8.employee import Employee

    _lock = lock(cfg)
    print(f"{cfg.employee.name} is on shift. Polling every {args.interval}s (Ctrl-C to stop)")
    Employee(cfg).work(args.interval, args.max_idle)
    return 0


def cmd_status(cfg: Config, _args) -> int:
    from deleg8.journal import Journal
    from deleg8.pm.base import make_pm

    tickets = make_pm(cfg).assigned()
    print(f"Open tickets assigned to {cfg.employee.name}:")
    for t in sorted(tickets, key=lambda t: int(t.id) if t.id.isdigit() else t.id):
        parent = f" (in #{t.parent})" if t.parent else ""
        print(f"  #{t.id:<4} {t.type:<6} {t.status:<12} {t.title[:70]}{parent}")
    print("\nRecent activity:")
    j = Journal(cfg.state_dir / "journal.db")
    total = 0.0
    for ts, ticket, phase, msg, cost, _link in j.recent(30):
        total += cost or 0
        print(f"  {time.strftime('%m-%d %H:%M', time.localtime(ts))} #{ticket:<4} {phase:<9} {msg[:90]}")
    print(f"\nmodel spend in the last 30 events: ${total:.2f}")
    return 0


def cmd_tool(cfg: Config, args) -> int:
    from deleg8.tools import ToolError, Tools

    t = Tools(cfg)
    fn = {
        "wiki-search": t.wiki_search,
        "wiki-read": t.wiki_read,
        "wiki-list": t.wiki_list,
        "db-list": t.db_list,
        "db-schema": t.db_schema,
        "db-query": t.db_query,
        "ticket-get": t.ticket_get,
        "ticket-search": t.ticket_search,
    }.get(args.name)
    if not fn:
        sys.exit(f"unknown tool {args.name}")
    try:
        print(fn(*args.args))
    except ToolError as e:
        print(f"ERROR: {e}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="deleg8", description="AI junior employee harness")
    ap.add_argument("--config", default=None, help="path to deleg8.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    b = sub.add_parser("bootstrap")
    b.add_argument("--visibility", choices=["public", "private"], default="public")
    b.add_argument("--skip-infra", action="store_true")
    s = sub.add_parser("seed")
    s.add_argument("--file", default=str(ROOT / "demo" / "tickets" / "seed.yaml"))
    s.add_argument("--only", nargs="*")
    r = sub.add_parser("run")
    r.add_argument("--ticket", help="work this ticket immediately")
    w = sub.add_parser("work")
    w.add_argument("--interval", type=int, default=60)
    w.add_argument("--max-idle", type=int, default=None, help="exit after N idle passes")
    sub.add_parser("status")
    t = sub.add_parser("tool")
    t.add_argument("name")
    t.add_argument("args", nargs="*")
    sub.add_parser("mcp")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    if args.cmd == "mcp":
        from deleg8.mcp_server import build_server
        from deleg8.tools import Tools

        build_server(Tools(cfg)).run()
        return
    handler = {
        "doctor": cmd_doctor,
        "bootstrap": cmd_bootstrap,
        "seed": cmd_seed,
        "run": cmd_run,
        "work": cmd_work,
        "status": cmd_status,
        "tool": cmd_tool,
    }[args.cmd]
    try:
        sys.exit(handler(cfg, args))
    except CommandError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
