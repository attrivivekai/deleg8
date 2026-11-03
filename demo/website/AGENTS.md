# Agent guide: deleg8-website

Read this before changing code. Humans and AI agents follow the same rules.

## Stack
- FastAPI + Jinja2 templates (`app/templates`), plain CSS (`app/static/style.css`), no JS framework.
- SQLAlchemy 2.0 models in `app/db.py`. Production uses Postgres, tests use SQLite.
  There are no migrations yet, and `Base.metadata.create_all` runs at startup. New tables are fine.
  Don't change existing columns without a ticket that says so.
- Marketing copy and pricing data live in `app/content.py`. Don't hard-code it in templates.

## Commands
- Install: `uv sync`
- Run locally: `uv run uvicorn app.main:app --reload`, then open http://localhost:8000
- Tests: `uv run pytest -q`
- Lint + format: `uv run ruff check . && uv run ruff format --check .` (auto-fix: `uv run ruff check --fix . && uv run ruff format .`)
- Static export (what GitHub Pages serves): `BASE_PATH=/deleg8-website uv run python scripts/freeze.py dist`

## Conventions
- Every new page or endpoint needs a test in `tests/`.
- Internal links in templates must use `{{ url('/path') }}` so the GitHub Pages sub-path works.
- New HTML pages must be parameter-less GET routes to be included in the static export automatically.
- Keep changes small and focused on the ticket. No drive-by refactors.
- Branch names: `deleg8/<ticket>-<slug>`. Commit messages use Conventional Commits (`feat:`, `fix:`, `docs:`, ...).

## Deploy
Merging to `main` triggers `.github/workflows/deploy.yml`, which publishes the static snapshot to GitHub Pages
and pushes a Docker image to GHCR.
