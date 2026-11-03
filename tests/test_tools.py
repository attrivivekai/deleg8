import pytest

from deleg8.agents.base import extract_json_block
from deleg8.models import AGENT_MARKER, Comment, Ticket, with_meta
from deleg8.tools import ToolError, Tools


def test_wiki_search_and_read(cfg):
    tools = Tools(cfg, pm=object())
    assert "product/pricing.md" in tools.wiki_search("popular plan")
    assert "90 days" in tools.wiki_read("product/pricing.md")
    with pytest.raises(ToolError):
        tools.wiki_read("../deleg8.yaml")


def test_db_query_sqlite_and_duckdb(cfg):
    tools = Tools(cfg, pm=object())
    assert "| 2 |" in tools.db_query("app", "SELECT COUNT(*) AS n FROM waitlist")
    out = tools.db_query("warehouse", "SELECT plan FROM demo_requests ORDER BY plan")
    assert "starter" in out and "team" in out
    assert "waitlist" in tools.db_schema("app")


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM waitlist",
        "SELECT 1; DROP TABLE waitlist",
        "UPDATE waitlist SET email='x'",
        "WITH x AS (SELECT 1) INSERT INTO waitlist VALUES (3,'z')",
    ],
)
def test_db_query_is_read_only(cfg, sql):
    with pytest.raises(ToolError):
        Tools(cfg, pm=object()).db_query("app", sql)


def test_ticket_meta_roundtrip():
    body = with_meta("Do the thing", {"parent": "3", "depends_on": ["4"], "repo": "site"})
    t = Ticket("5", "task", "x", body, "todo", "u")
    assert (t.parent, t.depends_on, t.repo) == ("3", ["4"], "site")
    assert "deleg8:meta" not in t.context_markdown()


def test_human_replied_since_agent():
    t = Ticket("1", "story", "x", "", "blocked", "u")
    t.comments = [Comment("bot", f"questions? {AGENT_MARKER}", "1")]
    assert not t.human_replied_since_agent()
    t.comments.append(Comment("pm", "here are answers", "2"))
    assert t.human_replied_since_agent()


def test_extract_json_block():
    assert extract_json_block('blah\n```json\n{"a": 1}\n```\n') == {"a": 1}
    assert extract_json_block('result: {"status": "done"}') == {"status": "done"}
