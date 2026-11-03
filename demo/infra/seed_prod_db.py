"""Generate demo/infra/initdb/02-seed.sql: a 'production' waitlist with a few bad emails in it."""

import random
from datetime import datetime, timedelta
from pathlib import Path

rnd = random.Random(42)
FIRST = ["ada", "grace", "linus", "margaret", "ken", "barbara", "alan", "radia", "guido", "anita",
         "dennis", "frances", "john", "hedy", "tim", "sophie", "yuki", "priya", "omar", "lena"]
DOMAINS = ["acme.io", "globex.com", "initech.dev", "umbrella.co", "hooli.com", "stark.ai",
           "wayne.tech", "cyberdyne.io", "soylent.co", "piedpiper.com"]
BAD = ["foo@", "@bar.com", "john@@example.com", "test@localhost", "a b@c.com", "hello@world",
       "@", "x@y", "no-at-sign.example.com"]  # last one can't exist (app requires '@')
SIZES = ["1-10", "11-50", "51-200", "201-1000", "1000+"]
PLANS = ["starter", "team", "enterprise"]


def esc(s: str) -> str:
    return s.replace("'", "''")


def main() -> None:
    now = datetime(2026, 11, 3, 12, 0)
    rows = []
    for i in range(300):
        name, dom = rnd.choice(FIRST), rnd.choice(DOMAINS)
        email = f"{name}{rnd.randint(1, 99)}@{dom}"
        company = dom.split(".")[0].title()
        rows.append((email, company))
    for bad in BAD[:-1]:
        rows.insert(rnd.randint(0, len(rows)), (bad, ""))
    lines = []
    for i, (email, company) in enumerate(rows):
        ts = now - timedelta(hours=(len(rows) - i) * 7)
        lines.append(
            "INSERT INTO waitlist_signups (email, company, team_size, plan_interest, created_at) "
            f"VALUES ('{esc(email)}', '{esc(company)}', '{rnd.choice(SIZES)}', "
            f"'{rnd.choices(PLANS, [0.4, 0.45, 0.15])[0]}', '{ts.isoformat()}+00');"
        )
    out = Path(__file__).parent / "initdb" / "02-seed.sql"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    print(f"wrote {len(lines)} rows to {out}")


if __name__ == "__main__":
    main()
