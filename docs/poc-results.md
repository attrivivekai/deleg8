# POC run: 2026-11-04

Dex (Claude Code headless: Sonnet 5.5 coding, Opus 5.5 planning/review) was pointed at the seed backlog in
[`attrivivekai/deleg8-website`](https://github.com/attrivivekai/deleg8-website/issues) and ran with
`deleg8 work --interval 30 --max-idle 2`. No human touched code, tickets or PRs during the run.

| ticket | kind | outcome |
|---|---|---|
| #1 invalid emails | bug | regex validation + tests, PR #13. Reported **8 of 308** prod rows invalid (count only, no PII), which matches the seeded ground truth |
| #2 public changelog | epic → #7 #8 #9 | data, page, nav/footer links. PRs #10 #14 #15. Exactly the 5 public milestones from the wiki, internal ones excluded, brand-voice tests |
| #3 data-driven pricing | epic → #5 #6 | "Most popular" = **Team** (192 vs 95 vs 73, last 90 days), correctly ignoring the all-time trap (Starter 749). FAQ copied verbatim from wiki. PRs #11 #12 |
| #4 "better for enterprise" | story | **blocked with 5 specific questions** (backed by warehouse conversion data). Refused to invent compliance claims |

* 7 tasks, 6 PRs, all AI-reviewed, CI-green, merged and auto-deployed to https://attrivivekai.github.io/deleg8-website/
* Total model cost **$2.91**, agent compute time 7.2 min, wall-clock **13.5 min** from first intake to last epic report
* Each epic got a completion report with the evidence behind its decisions (SQL + results, wiki references)

## Issues found and fixed in the harness after the run
* The coding agent sometimes put `(#N)` in its own commit subject, so the harness's suffix doubled it. Now de-duplicated.
* Epic reports only saw each task's completion comment, so the reporter couldn't confirm tests/CI/deploy. It now gets
  each task's journal trail (changed files, checks, review verdict, CI result) and the latest deploy run status.
