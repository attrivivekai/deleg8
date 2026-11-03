"""Append-only audit journal of everything the AI employee does (SQLite)."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path


class Journal:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path)
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS events (
                 id INTEGER PRIMARY KEY, ts REAL, ticket TEXT, phase TEXT, message TEXT,
                 cost_usd REAL DEFAULT 0, duration_s REAL DEFAULT 0, link TEXT DEFAULT '')"""
        )
        self.db.commit()

    def log(
        self,
        ticket: str,
        phase: str,
        message: str,
        cost_usd: float = 0.0,
        duration_s: float = 0.0,
        link: str = "",
    ) -> None:
        self.db.execute(
            "INSERT INTO events (ts, ticket, phase, message, cost_usd, duration_s, link) VALUES (?,?,?,?,?,?,?)",
            (time.time(), str(ticket), phase, message, cost_usd, duration_s, link),
        )
        self.db.commit()
        stamp = time.strftime("%H:%M:%S")
        cost = f" (${cost_usd:.2f}, {duration_s:.0f}s)" if cost_usd or duration_s else ""
        print(f"[{stamp}] #{ticket:<5} {phase:<10} {message}{cost}", flush=True)

    def totals(self, tickets: list[str]) -> tuple[float, float, float, float]:
        """cost, agent seconds, first ts, last ts for a set of tickets."""
        if not tickets:
            return 0.0, 0.0, 0.0, 0.0
        q = ",".join("?" * len(tickets))
        row = self.db.execute(
            f"SELECT COALESCE(SUM(cost_usd),0), COALESCE(SUM(duration_s),0), MIN(ts), MAX(ts) "
            f"FROM events WHERE ticket IN ({q})",
            [str(t) for t in tickets],
        ).fetchone()
        return row[0], row[1], row[2] or 0, row[3] or 0

    def recent(self, limit: int = 40) -> list[tuple]:
        return self.db.execute(
            "SELECT ts, ticket, phase, message, cost_usd, link FROM events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()[::-1]

    def trail(self, ticket: str) -> list[str]:
        rows = self.db.execute("SELECT phase, message FROM events WHERE ticket = ? ORDER BY id", (str(ticket),))
        return [f"{phase}: {msg}" for phase, msg in rows]

    def all(self) -> list[tuple]:
        return self.db.execute(
            "SELECT ts, ticket, phase, message, cost_usd, duration_s, link FROM events ORDER BY id"
        ).fetchall()
