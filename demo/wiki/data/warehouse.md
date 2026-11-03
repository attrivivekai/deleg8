# Analytics warehouse (DuckDB)

Read-only access through the deleg8 `warehouse` tool. Refreshed nightly from product analytics and CRM.

## Tables
### `demo_requests`
One row per demo request from the sales funnel.
| column | type | notes |
|---|---|---|
| id | int | |
| requested_at | timestamp | UTC |
| plan | varchar | `starter` / `team` / `enterprise` |
| company_size | varchar | `1-10`, `11-50`, `51-200`, `201-1000`, `1000+` |
| source | varchar | `organic`, `twitter`, `hn`, `referral`, `ads` |
| converted | boolean | became a paying customer |

### `web_sessions`
Daily sessions per page and traffic source: `day date, page varchar, source varchar, sessions int`.

### `mrr_monthly`
`month date, plan varchar, mrr_usd decimal`

## Metric definitions
- **Most popular plan** = plan with the most `demo_requests` rows where `requested_at >= now() - interval 90 day`.
- **Conversion rate** = converted / total demo requests in the period.
