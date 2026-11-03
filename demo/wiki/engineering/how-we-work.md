# How we work

## Tickets
- Work is tracked in GitHub Issues on `attrivivekai/deleg8-website`.
- Labels: `type:epic`, `type:story`, `type:task`, `type:bug`; status labels `status:todo`, `status:in-progress`,
  `status:in-review`, `status:blocked`. Closed = done.
- Tickets labelled `deleg8` are assigned to our AI junior, **Dex**.

## Definition of done
1. Acceptance criteria met, with tests for new behavior.
2. `ruff check`, `ruff format --check` and `pytest` pass locally and in CI.
3. PR description links the ticket (`Closes #N`) and explains *what* and *why*.
4. Reviewed (AI reviewer for Dex's PRs; humans can always add a review).
5. Deployed: merging to `main` auto-deploys to GitHub Pages.

## Escalation
If a ticket is ambiguous, don't guess. Ask specific questions on the ticket and mark it `status:blocked`.
