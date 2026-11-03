# Architecture

```
browser ──► FastAPI (app/main.py) ──► SQLAlchemy ──► Postgres (prod) / SQLite (dev, tests)
              │
              └── Jinja2 templates + static CSS/JS
```

* `GET /`, `/how-it-works`, `/pricing`, `/thanks`: marketing pages
* `POST /waitlist` (form) and `POST /api/waitlist` (JSON): create a `waitlist_signups` row
* `GET /api/waitlist/count`: total signups
* `GET /api/health`: liveness check

## Data
`waitlist_signups(id, email, company, team_size, plan_interest, created_at)`

Analytics (sessions, demo requests, revenue) live in the **DuckDB warehouse** maintained by the data team,
not in the app database. Ask deleg8 tools `warehouse` for them.

## Environments
| env | where | data |
|---|---|---|
| local | `uv run uvicorn app.main:app` | SQLite `./deleg8.db` |
| prod-like | `docker compose up` | Postgres on :5433 |
| preview | GitHub Pages static snapshot | none, so forms are disabled |
