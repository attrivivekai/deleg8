# deleg8: AI junior employees that work from your tickets

**deleg8** is a harness that turns a coding agent (Claude Code, pi, ...) into an autonomous **junior employee**.
It doesn't wait for prompts. It takes work from your project tracker the way a new hire does:

1. **Intake**: picks up epics, stories and bugs assigned to it in the PM tool.
2. **Research**: reads the repo, the company wiki, the production DB and the analytics warehouse (read-only, via MCP).
3. **Plan**: breaks epics/stories into small tasks, **creates them as tickets**, and posts a plan with research evidence.
   If the ticket is too vague it **asks clarifying questions and marks it blocked** instead of guessing.
4. **Execute**: for each task, in dependency order: branch → coding harness → local checks (fix loop) → PR.
5. **Review**: a separate model run acts as a senior reviewer. If it requests changes, the work loops back to the coder.
6. **CI/CD**: waits for GitHub Actions and feeds CI failure logs back to the coder, then merges, which deploys.
7. **Report**: moves tickets to Done, and when an epic is finished posts a **completion report** with what shipped,
   decisions and evidence, plus time and model cost.

Everything is logged to an audit journal (`.deleg8/journal.db`), and every model transcript is kept in `.deleg8/logs/`.

```
          ┌───────────── PM tool (GitHub Issues / Jira) ─────────────┐
          │  epic ──► tasks (created by deleg8) ──► status / comments  │
          └───────────────▲───────────────────────────────┬──────────┘
                          │ tickets in, updates out        │
                 ┌────────┴────────────────────────────────▼────────┐
                 │                deleg8 employee loop               │
                 │ intake → plan → execute → review → CI → merge → report
                 └──┬──────────────┬──────────────────┬─────────────┘
          think()   │      work()  │                  │ git / gh
      (read-only)   ▼              ▼                  ▼
            ┌──────────────┐ ┌──────────────┐  ┌───────────────────────┐
            │ brain harness│ │coding harness│  │ GitHub repo + Actions │
            │ (Claude Code)│ │ (Claude Code │  │ PRs · CI · deploy     │
            └──────┬───────┘ │   or pi)     │  └───────────────────────┘
                   │         └──────┬───────┘
                   ▼ MCP / CLI      ▼
          ┌─────────────────────────────────────────────┐
          │ deleg8 research tools (read-only)            │
          │ wiki · Postgres (prod) · DuckDB (warehouse) · tickets │
          └─────────────────────────────────────────────┘
```

## The proof-of-concept company

This repo ships a whole **"company in a box"**, so the employee has a real workplace:

| piece | what | tech (free / open source) |
|---|---|---|
| Website repo | [`attrivivekai/deleg8-website`](https://github.com/attrivivekai/deleg8-website): deleg8's marketing site + waitlist | FastAPI, Jinja2, SQLAlchemy |
| Project management | GitHub Issues with epics/stories/tasks/bugs as labels + sub-issues | GitHub Issues (Jira adapter included) |
| CI | lint + format + tests + static-export smoke test on every PR | GitHub Actions |
| CD | merge to `main` → static snapshot on GitHub Pages + Docker image to GHCR | GitHub Pages, GHCR |
| Production DB | seeded waitlist, read-only role `dex_readonly` | Postgres 16 (Docker) |
| Warehouse | demo requests, web sessions, MRR | DuckDB |
| Team wiki | handbook, brand voice, pricing decisions, data docs | Markdown (`demo/wiki`) |
| Coding harness | implements tasks | Claude Code headless (`claude -p`) or pi |

The seed backlog (`demo/tickets/seed.yaml`) is written like real PM tickets, and each one tests a different skill:

* **Bug: invalid emails accepted**: fix + tests, and *report how many production rows are invalid* (DB research, PII-safe).
* **Epic: public changelog**: content must come from the wiki timeline, include only public milestones, and follow brand voice.
* **Epic: data-driven pricing**: "Most popular" badge chosen from **warehouse data** using the wiki's metric definition
  (all-time data says Starter, the correct 90-day metric says Team), plus an FAQ that uses the wiki's approved answers verbatim.
* **Story: "make it better for enterprise"**: deliberately vague, so the employee should **ask questions, not guess**.

## Quick start

```bash
uv sync                                  # install the harness
gh auth login                            # GitHub API access (repo, workflow scopes)
uv run deleg8 bootstrap                  # create website repo, push code + CI/CD, enable Pages, labels,
                                         # build warehouse, start prod Postgres
uv run deleg8 seed                       # create the backlog as GitHub Issues
uv run deleg8 doctor                     # verify every tool is reachable
uv run deleg8 run                        # one pass over the backlog
uv run deleg8 work --interval 60         # ...or keep the employee "on shift"
uv run deleg8 status                     # board + activity journal
```

Work a specific ticket immediately: `uv run deleg8 run --ticket 3`.

## Configuration (`deleg8.yaml`)

One file onboards an employee: identity, PM tool, repos (with setup + check commands), research access,
which harness/model to use for coding vs. thinking, and **policy** guardrails:

```yaml
policy:
  auto_merge: true        # false = every PR waits for a human approval
  ai_review: true         # senior-reviewer model pass before CI
  max_fix_attempts: 2     # per failure type (local checks / CI)
  max_tasks_per_epic: 6
```

## Design notes

* **Tool-agnostic core.** `pm/` (GitHub Issues, Jira), `agents/` (Claude Code, pi) and `tools.py` are adapters.
  A new PM tool or harness is roughly 150 lines.
* **Same tools over MCP and CLI.** Claude Code gets the research tools as an MCP server (`deleg8 mcp`). Shell-only
  harnesses (pi) call `deleg8 tool db-query warehouse "SELECT ..."`.
* **Least privilege.** The planner and reviewer run with read-only tools (`--allowedTools Read Grep Glob mcp__deleg8`).
  SQL is checked for being a single read-only statement *and* runs on read-only connections/roles.
* **The harness owns git.** Coding agents edit the working tree only. deleg8 verifies the checks, commits, pushes and opens
  PRs, so a model can't skip verification.
* **Escalation is a feature.** Blocked tickets carry specific questions, and a human reply unblocks them on the next pass.
* **State lives in the PM tool.** Status labels, sub-issues and a hidden metadata block (`parent`, `depends_on`, `repo`)
  hold the state, so the loop is restartable and humans can intervene at any point.

## Layout

```
src/deleg8/
  employee.py      the workflow / state machine
  pm/              github.py (Issues + sub-issues), jira.py (Jira Cloud REST v3)
  agents/          claude_code.py, pi.py
  tools.py         wiki / SQL / ticket research tools   mcp_server.py   MCP wrapper
  scm.py           workspaces, git, PRs, CI checks, merge
  prompts.py       phase prompts + JSON output schemas
  journal.py       audit trail with cost/time
demo/
  website/         template for the deleg8-website repo (pushed by `bootstrap`)
  wiki/            company handbook        warehouse/   DuckDB builder
  infra/           Postgres "production" + seed + read-only role
  tickets/         seed backlog
tests/             offline tests of the whole workflow with fake PM/harness/CI
```

## Limitations / next steps

* Runs tasks sequentially. Parallel tasks would use one git worktree per task.
* The employee acts through your `gh` identity, so give it a dedicated bot account / GitHub App in production.
* The Jira adapter is implemented against the documented REST v3 API but wasn't exercised in this POC (no Jira site).
* Add Slack/email escalation, a web dashboard, and per-ticket budget caps (the harness already passes `--max-budget-usd`).
