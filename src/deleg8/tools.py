"""Research tools the AI employee can use: company wiki, read-only databases, tickets.

The same functions back the MCP server (`deleg8 mcp`) and the CLI (`deleg8 tool ...`), so they work with
any coding harness: MCP-capable ones (Claude Code) or shell-only ones (pi).
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from deleg8.config import Config

MAX_ROWS = 200
_READONLY_SQL = re.compile(r"^\s*(select|with|show|describe|explain|pragma|summarize)\b", re.I)
_FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|attach|detach|install|load)\b",
    re.I,
)


class ToolError(Exception):
    pass


class Tools:
    def __init__(self, cfg: Config, pm=None):
        self.cfg = cfg
        self._pm = pm

    @property
    def pm(self):
        if self._pm is None:
            from deleg8.pm.base import make_pm

            self._pm = make_pm(self.cfg)
        return self._pm

    # ------------------------------------------------------------------ wiki
    def _wiki_files(self) -> list[tuple[Path, Path]]:
        files = []
        for root in self.cfg.wiki_dirs:
            files += [(root, p) for p in sorted(root.rglob("*.md"))]
        return files

    def wiki_list(self) -> str:
        return "\n".join(str(p.relative_to(root)) for root, p in self._wiki_files()) or "(wiki is empty)"

    def wiki_search(self, query: str, limit: int = 8) -> str:
        terms = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 2]
        hits = []
        for root, p in self._wiki_files():
            text = p.read_text(errors="ignore")
            low = text.lower()
            score = sum(low.count(t) for t in terms)
            if score:
                lines = [ln for ln in text.splitlines() if any(t in ln.lower() for t in terms)][:4]
                hits.append((score, str(p.relative_to(root)), lines))
        hits.sort(reverse=True)
        if not hits:
            return f"No wiki pages match {query!r}. Pages:\n{self.wiki_list()}"
        return "\n\n".join(
            f"## {path} (score {score})\n" + "\n".join(f"> {ln.strip()}" for ln in lines)
            for score, path, lines in hits[:limit]
        )

    def wiki_read(self, path: str) -> str:
        for root in self.cfg.wiki_dirs:
            p = (root / path).resolve()
            if p.is_relative_to(root) and p.is_file():
                return p.read_text()
        raise ToolError(f"wiki page {path!r} not found. Pages:\n{self.wiki_list()}")

    # ------------------------------------------------------------- databases
    def db_list(self) -> str:
        return "\n".join(f"- {name}: {spec.get('description', '')}" for name, spec in self.cfg.databases.items())

    def db_query(self, database: str, sql: str) -> str:
        spec = self.cfg.databases.get(database)
        if not spec:
            raise ToolError(f"unknown database {database!r}. Available:\n{self.db_list()}")
        sql = sql.strip().rstrip(";")
        if ";" in sql or not _READONLY_SQL.match(sql) or _FORBIDDEN_SQL.search(sql):
            raise ToolError("Only single read-only statements (SELECT/WITH/DESCRIBE/SHOW/EXPLAIN) allowed.")
        cols, rows = _execute_readonly(spec["url"], sql)
        return format_table(cols, rows)

    def db_schema(self, database: str) -> str:
        url = self.cfg.databases.get(database, {}).get("url", "")
        if url.startswith("postgresql"):
            q = (
                "SELECT table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' ORDER BY table_name, ordinal_position"
            )
        elif url.startswith("sqlite"):
            q = (
                "SELECT m.name AS table_name, p.name AS column_name, p.type AS data_type "
                "FROM sqlite_master m JOIN pragma_table_info(m.name) p WHERE m.type = 'table'"
            )
        else:
            q = (
                "SELECT table_name, column_name, data_type FROM information_schema.columns "
                "ORDER BY table_name, ordinal_position"
            )
        return self.db_query(database, q)

    # --------------------------------------------------------------- tickets
    def ticket_get(self, ticket_id: str) -> str:
        return self.pm.get(ticket_id).context_markdown()

    def ticket_search(self, query: str) -> str:
        tickets = self.pm.search(query)
        return "\n".join(f"- {t.id} [{t.type}/{t.status}] {t.title} ({t.url})" for t in tickets) or "none"


def _execute_readonly(url: str, sql: str) -> tuple[list[str], list[tuple]]:
    if url.startswith("duckdb:///"):
        import duckdb

        con = duckdb.connect(url.removeprefix("duckdb:///"), read_only=True)
        try:
            cur = con.execute(sql)
            return [d[0] for d in cur.description], cur.fetchmany(MAX_ROWS)
        finally:
            con.close()
    if url.startswith("sqlite:///"):
        con = sqlite3.connect(f"file:{url.removeprefix('sqlite:///')}?mode=ro", uri=True)
        try:
            cur = con.execute(sql)
            return [d[0] for d in cur.description], cur.fetchmany(MAX_ROWS)
        finally:
            con.close()
    if url.startswith(("postgresql://", "postgres://")):
        import psycopg

        with psycopg.connect(url, connect_timeout=5) as con:
            con.read_only = True
            with con.cursor() as cur:
                cur.execute(sql)
                return [d.name for d in cur.description], cur.fetchmany(MAX_ROWS)
    raise ToolError(f"unsupported database url scheme: {url.split(':', 1)[0]}")


def format_table(cols: list[str], rows: list[tuple]) -> str:
    if not rows:
        return " | ".join(cols) + "\n(0 rows)"
    head = "| " + " | ".join(cols) + " |"
    sep = "|" + "---|" * len(cols)
    body = ["| " + " | ".join(str(v) for v in r) + " |" for r in rows]
    more = f"\n(truncated to {MAX_ROWS} rows)" if len(rows) >= MAX_ROWS else ""
    return "\n".join([head, sep, *body]) + more
