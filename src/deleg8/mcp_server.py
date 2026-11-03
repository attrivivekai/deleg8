"""MCP server exposing deleg8's research tools to MCP-capable coding harnesses (e.g. Claude Code).

Run: python -m deleg8.mcp_server --config deleg8.yaml   (stdio transport)
"""

from __future__ import annotations

import argparse

from mcp.server.mcpserver import MCPServer

from deleg8.config import load_config
from deleg8.tools import ToolError, Tools


def build_server(tools: Tools) -> MCPServer:
    mcp = MCPServer("deleg8", instructions="deleg8 company research tools: wiki, read-only databases, tickets.")

    def safe(fn, *a):
        try:
            return fn(*a)
        except ToolError as e:
            return f"ERROR: {e}"
        except Exception as e:  # surface infra errors to the model instead of crashing the server
            return f"ERROR ({type(e).__name__}): {e}"

    @mcp.tool()
    def wiki_search(query: str) -> str:
        """Full-text search the company wiki (handbook, product decisions, data docs, brand voice)."""
        return safe(tools.wiki_search, query)

    @mcp.tool()
    def wiki_read(path: str) -> str:
        """Read a wiki page by its relative path, e.g. 'product/pricing.md'."""
        return safe(tools.wiki_read, path)

    @mcp.tool()
    def wiki_list() -> str:
        """List all wiki pages."""
        return safe(tools.wiki_list)

    @mcp.tool()
    def db_list() -> str:
        """List the databases/warehouses you can query (read-only)."""
        return safe(tools.db_list)

    @mcp.tool()
    def db_schema(database: str) -> str:
        """Show tables and columns of a database, e.g. database='warehouse' or 'app'."""
        return safe(tools.db_schema, database)

    @mcp.tool()
    def db_query(database: str, sql: str) -> str:
        """Run ONE read-only SQL statement (SELECT/WITH/...) against a database. Max 200 rows returned."""
        return safe(tools.db_query, database, sql)

    @mcp.tool()
    def ticket_get(ticket_id: str) -> str:
        """Fetch a ticket (epic/story/task/bug) with description and discussion from the project tracker."""
        return safe(tools.ticket_get, ticket_id)

    @mcp.tool()
    def ticket_search(query: str) -> str:
        """Search tickets in the project tracker."""
        return safe(tools.ticket_search, query)

    return mcp


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="deleg8.yaml")
    args = ap.parse_args()
    build_server(Tools(load_config(args.config))).run()


if __name__ == "__main__":
    main()
