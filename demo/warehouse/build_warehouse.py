"""Build the demo analytics warehouse (DuckDB) with deterministic, realistic-looking data.

Usage: python demo/warehouse/build_warehouse.py [out_path]

Designed so that all-time "most requested plan" (starter, skewed by early beta)
differs from the last-90-days answer (team). Agents must read the metric definition.
"""

import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

import duckdb

PLANS = ["starter", "team", "enterprise"]
SIZES = ["1-10", "11-50", "51-200", "201-1000", "1000+"]
SOURCES = ["organic", "twitter", "hn", "referral", "ads"]
PAGES = ["/", "/how-it-works", "/pricing", "/thanks"]


def build(out: Path, today: datetime | None = None) -> Path:
    rnd = random.Random(8)
    today = (today or datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    con = duckdb.connect(str(out))

    con.execute(
        """CREATE TABLE demo_requests (id INTEGER, requested_at TIMESTAMP, plan VARCHAR,
           company_size VARCHAR, source VARCHAR, converted BOOLEAN)"""
    )
    rows, rid = [], 1
    for days_ago in range(240, -1, -1):
        day = today - timedelta(days=days_ago)
        recent = days_ago < 90
        # early beta: starter-heavy, recent: team-heavy
        weights = [0.25, 0.55, 0.20] if recent else [0.70, 0.22, 0.08]
        for _ in range(rnd.randint(2, 6) if recent else rnd.randint(4, 9)):
            plan = rnd.choices(PLANS, weights)[0]
            ts = day + timedelta(minutes=rnd.randint(0, 1439))
            rows.append((rid, ts, plan, rnd.choice(SIZES), rnd.choice(SOURCES), rnd.random() < 0.18))
            rid += 1
    con.executemany("INSERT INTO demo_requests VALUES (?, ?, ?, ?, ?, ?)", rows)

    con.execute("CREATE TABLE web_sessions (day DATE, page VARCHAR, source VARCHAR, sessions INTEGER)")
    sess = []
    for days_ago in range(120, -1, -1):
        day = (today - timedelta(days=days_ago)).date()
        for page in PAGES:
            for src in SOURCES:
                base = {"/": 120, "/pricing": 45, "/how-it-works": 30, "/thanks": 4}[page]
                sess.append((day, page, src, max(0, int(rnd.gauss(base / 5, base / 15)))))
    con.executemany("INSERT INTO web_sessions VALUES (?, ?, ?, ?)", sess)

    con.execute("CREATE TABLE mrr_monthly (month DATE, plan VARCHAR, mrr_usd DECIMAL(12,2))")
    mrr = []
    for m in range(6, -1, -1):
        month = (today.replace(day=1) - timedelta(days=30 * m)).replace(day=1).date()
        growth = 7 - m
        mrr += [
            (month, "starter", 499 * (2 + growth)),
            (month, "team", 1999 * max(0, growth - 1)),
            (month, "enterprise", 12000 * (1 if growth > 4 else 0)),
        ]
    con.executemany("INSERT INTO mrr_monthly VALUES (?, ?, ?)", mrr)
    con.close()
    return out


if __name__ == "__main__":
    default = Path(__file__).parent / "warehouse.duckdb"
    path = build(Path(sys.argv[1]) if len(sys.argv) > 1 else default)
    print(f"warehouse built at {path}")
