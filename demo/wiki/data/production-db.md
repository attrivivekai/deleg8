# Production database (Postgres)

The website's app database. AI employees get a **read-only** role through the deleg8 `app` database tool.

- Table `waitlist_signups(id, email, company, team_size, plan_interest, created_at)`.
- Never copy personal data (emails) into tickets or PRs. Report counts and anonymized examples only
  (e.g. `j***@example.com`).
