"""Prompts and output schemas for each phase of the employee's workflow."""

from __future__ import annotations

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "understanding": {"type": "string", "description": "What is being asked, in your own words"},
        "research_notes": {
            "type": "string",
            "description": "Markdown: what you looked up (wiki pages, SQL queries + results, code) and what "
            "you learned. Include exact queries and numbers when data informed a decision.",
        },
        "sufficient": {"type": "boolean", "description": "false if the ticket is too ambiguous to plan"},
        "questions": {"type": "array", "items": {"type": "string"}},
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {
                        "type": "string",
                        "description": "Markdown: context + implementation notes",
                    },
                    "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                    "repo": {"type": "string"},
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "0-based indexes of earlier tasks in this list",
                    },
                },
                "required": ["title", "description", "acceptance_criteria", "depends_on"],
            },
        },
    },
    "required": ["understanding", "research_notes", "sufficient", "questions", "tasks"],
}

WORK_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["done", "blocked"]},
        "summary": {"type": "string", "description": "Markdown summary of what you changed and why"},
        "commit_message": {"type": "string", "description": "Conventional Commit subject line"},
        "tests": {"type": "string", "description": "Which checks you ran and their result"},
        "ticket_notes": {
            "type": "string",
            "description": "Anything the ticket explicitly asked you to report (numbers, decisions, "
            "evidence such as SQL + result). Empty if nothing.",
        },
        "questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "summary", "commit_message", "tests", "ticket_notes", "questions"],
}

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["approve", "request_changes"]},
        "summary": {"type": "string"},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["blocker", "major", "minor", "nit"]},
                    "file": {"type": "string"},
                    "comment": {"type": "string"},
                },
                "required": ["severity", "comment"],
            },
        },
    },
    "required": ["verdict", "summary", "issues"],
}

REPORT_SCHEMA = {
    "type": "object",
    "properties": {"report": {"type": "string", "description": "Markdown report"}},
    "required": ["report"],
}


def plan_prompt(ticket_md: str, repos: str, max_tasks: int) -> str:
    return f"""You have been assigned this ticket from the project tracker:

{ticket_md}

Available repositories (the current directory is a checkout of the first one):
{repos}

Your job now is RESEARCH and PLANNING only. Do not change any files.

1. Research: read the repo (AGENTS.md/CLAUDE.md, relevant code), search the company wiki, and query the
   databases/warehouse when the ticket depends on data. Record what you found, with exact SQL and results.
2. If the ticket is too ambiguous to plan responsibly (unclear goal, no acceptance criteria you can infer,
   conflicting requirements), set sufficient=false and ask 2-5 specific questions. Do not invent requirements.
3. Otherwise break it into at most {max_tasks} small, independently shippable tasks. Each task becomes one pull
   request. Order them so dependencies come first, and keep tests with the code they test (no separate
   "write tests" task). Put the decisions from your research INTO the task descriptions (e.g. "the most
   popular plan is `team`: 412 requests in the last 90 days"), because the engineer implementing a task will see
   the task, not your research notes.
"""


def work_prompt(task_md: str, parent_md: str, repo_checks: str, extra: str = "") -> str:
    parent = f"\n\nIt is part of this larger ticket (for context only):\n\n{parent_md}" if parent_md else ""
    return f"""Implement this ticket in the repository in the current directory.

{task_md}{parent}

How to work:
- Read AGENTS.md / CLAUDE.md first and follow its conventions. Look at the existing code and tests.
- Use the deleg8 research tools (wiki, databases, tickets) if you need company context or data.
- Make the smallest change that fully meets the acceptance criteria, and add or update tests.
- Run the project's checks and make them pass before finishing:
{repo_checks}
- Do NOT commit, push or create branches. The harness does that after verifying your work.
- If the ticket cannot be done as written (missing information, contradicts the codebase), stop and return
  status=blocked with specific questions instead of guessing.
{extra}"""


def fix_prompt(kind: str, details: str) -> str:
    return f"""Your previous change for this ticket needs another iteration: {kind}.

{details}

Fix the problems in the working tree (do not commit), re-run the checks, and report again."""


def review_prompt(ticket_md: str, diff: str, checks: str) -> str:
    return f"""You are reviewing a pull request written by an AI junior engineer, as a senior reviewer.

Ticket:
{ticket_md}

Local check results:
{checks}

Diff:
```diff
{diff[:60000]}
```

Review for: correctness against the acceptance criteria, missing tests, security/privacy issues (e.g. personal
data in code or docs), regressions, and violations of the repo conventions (read AGENTS.md if needed). You may
read files in the repo for context. Approve if it is ready to merge. Only request changes for blocker or major
issues. Nits alone are not a reason to block."""


def report_prompt(ticket_md: str, children_md: str, stats: str) -> str:
    return f"""All tasks for this ticket are complete. Write the completion report for stakeholders.

Ticket:
{ticket_md}

Completed tasks, PRs and notes:
{children_md}

Execution stats:
{stats}

Write a concise Markdown report: outcome (1-2 sentences), what shipped (bullets with PR links), key decisions
and the evidence behind them (data, wiki references), how it was verified (tests/CI/deploy), and follow-ups or
risks. Write for a product manager. No fluff."""
