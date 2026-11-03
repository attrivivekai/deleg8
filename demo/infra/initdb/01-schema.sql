-- "Production" schema for the deleg8 website (mirrors app/db.py)
CREATE TABLE IF NOT EXISTS waitlist_signups (
    id SERIAL PRIMARY KEY,
    email VARCHAR(320) NOT NULL,
    company VARCHAR(200) NOT NULL DEFAULT '',
    team_size VARCHAR(20) NOT NULL DEFAULT '1-10',
    plan_interest VARCHAR(20) NOT NULL DEFAULT 'starter',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_waitlist_signups_email ON waitlist_signups (email);
