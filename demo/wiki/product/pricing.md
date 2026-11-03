# Pricing

Plans live in `app/content.py` in the website repo (`starter`, `team`, `enterprise`).

## Decisions
- 2026-09: We highlight **one** plan as "Most popular" on the pricing page. It must be the plan with the most
  demo requests in the **last 90 days**, as measured in the warehouse (`demo_requests`, see data/warehouse.md).
  Do not use all-time numbers, because early-beta traffic skews them toward Starter.
- Prices are monthly, in USD, billed per AI employee seat. No annual discount yet.

## FAQ (approved answers, use verbatim on the website)
**Does deleg8 write to my production database?**
No. Database and warehouse access is read-only. Changes ship only through pull requests and your CI.

**Which coding harnesses are supported?**
Claude Code and pi today. Anything with a headless mode can be added as an adapter.

**Can a human review before merge?**
Yes. Auto-merge is a policy setting. Turn it off and every PR waits for a human approval.

**What happens when a ticket is unclear?**
The AI junior asks clarifying questions on the ticket and marks it blocked until someone answers.
