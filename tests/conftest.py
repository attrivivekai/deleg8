import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fakes import FakePRs, FakeWorkspace  # noqa: E402

from deleg8 import employee as employee_mod  # noqa: E402
from deleg8.config import load_config  # noqa: E402
from deleg8.journal import Journal  # noqa: E402


@pytest.fixture()
def cfg(tmp_path):
    wiki = tmp_path / "wiki"
    (wiki / "product").mkdir(parents=True)
    (wiki / "product" / "pricing.md").write_text("# Pricing\nMost popular plan uses last 90 days.\n")
    con = sqlite3.connect(tmp_path / "app.db")
    con.execute("CREATE TABLE waitlist (id INTEGER, email TEXT)")
    con.executemany("INSERT INTO waitlist VALUES (?, ?)", [(1, "a@b.co"), (2, "foo@")])
    con.commit()
    con.close()
    import duckdb

    wh = duckdb.connect(str(tmp_path / "wh.duckdb"))
    wh.execute("CREATE TABLE demo_requests AS SELECT 'team' AS plan UNION ALL SELECT 'starter'")
    wh.close()
    (tmp_path / "deleg8.yaml").write_text(
        """
employee: {name: Testy}
pm: {provider: github, github: {repo: o/r}}
repos:
  - {name: site, github: o/site, checks: ["true"]}
knowledge:
  wiki_dirs: [wiki]
  databases:
    app: {url: "sqlite:///app.db", description: app db}
    warehouse: {url: "duckdb:///wh.duckdb", description: warehouse}
policy: {max_fix_attempts: 1, max_review_rounds: 1}
"""
    )
    return load_config(tmp_path / "deleg8.yaml")


@pytest.fixture()
def fakes(monkeypatch, cfg):
    FakeWorkspace.instances.clear()
    FakeWorkspace.checks_ok = True
    FakePRs.merged = []
    FakePRs.ci_results = []
    monkeypatch.setattr(employee_mod, "Workspace", FakeWorkspace)
    monkeypatch.setattr(employee_mod, "GitHubPRs", FakePRs)
    return Journal(cfg.state_dir / "journal.db")
