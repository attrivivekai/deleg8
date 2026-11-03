"""The AI employee: an event loop that works the backlog the way a junior engineer would.

intake ─► research & plan (epics/stories) ─► tasks in PM tool
             │ unclear? ask questions, mark blocked, wait for a human reply
task ─► branch ─► coding harness ─► local checks ─► PR ─► AI review ─► CI ─► merge ─► ticket done
                      ▲   fix loop (checks / review / CI failures)  │
all tasks done ─► completion report on the epic ─► epic done
"""

from __future__ import annotations

import re
import time
from datetime import datetime

from deleg8.agents.base import AgentResult, CodingHarness, make_harness
from deleg8.config import Config, RepoConfig
from deleg8.journal import Journal
from deleg8.models import Ticket
from deleg8.pm.base import ProjectManager, make_pm
from deleg8.prompts import (
    PLAN_SCHEMA,
    REPORT_SCHEMA,
    REVIEW_SCHEMA,
    WORK_SCHEMA,
    fix_prompt,
    plan_prompt,
    report_prompt,
    review_prompt,
    work_prompt,
)
from deleg8.scm import GitHubPRs, Workspace, slugify


class Blocked(Exception):
    """The employee needs a human: posts the message on the ticket and marks it blocked."""


class Employee:
    def __init__(
        self,
        cfg: Config,
        pm: ProjectManager | None = None,
        coder: CodingHarness | None = None,
        brain: CodingHarness | None = None,
        journal: Journal | None = None,
    ):
        self.cfg = cfg
        self.pm = pm or make_pm(cfg)
        self.coder = coder or make_harness(cfg, "coding")
        self.brain = brain or make_harness(cfg, "brain")
        self.journal = journal or Journal(cfg.state_dir / "journal.db")
        self.sig = cfg.employee.signature

    # ================================================================ loop
    def run_once(self) -> int:
        """One pass over the backlog. Returns the number of actions taken."""
        actions = 0
        tickets = self.pm.assigned()

        for t in tickets:  # 1. humans answered my questions? -> back to todo
            if t.status == "blocked" and t.human_replied_since_agent():
                self.pm.set_status(t.id, "todo")
                self.pm.comment(t.id, "Thanks for the reply. Picking this back up.", self.sig)
                self.journal.log(t.id, "unblocked", "human replied, resuming")
                actions += 1
        if actions:
            tickets = self.pm.assigned()

        for t in tickets:  # 2. research + plan new epics/stories
            if t.is_container and not t.planned and t.status != "blocked":
                self._guard(t, self.plan)
                actions += 1

        done_ids: dict[str, bool] = {}
        executed = 0
        for t in self.pm.assigned():  # 3. resume PRs, 4. execute ready tasks
            if t.is_container or t.status in ("blocked", "done"):
                continue
            if executed >= self.cfg.policy.max_tasks_per_run:
                break
            if t.status == "in-review":
                self._guard(t, self.resume_review)
                actions += 1
                continue
            if all(self._is_done(d, done_ids) for d in t.depends_on):
                self._guard(t, self.execute)
                executed += 1
                actions += 1

        for t in self.pm.assigned():  # 5. close out finished epics/stories
            if t.is_container and t.planned and t.status != "blocked":
                kids = self.pm.children(t.id)
                if kids and all(k.status == "done" for k in kids):
                    self._guard(t, lambda tt, kids=kids: self.finalize(tt, kids))
                    actions += 1
        return actions

    def work(self, interval_s: int = 60, max_idle_passes: int | None = None) -> None:
        idle = 0
        while True:
            n = self.run_once()
            idle = 0 if n else idle + 1
            if max_idle_passes is not None and idle >= max_idle_passes:
                return
            time.sleep(interval_s if not n else 2)

    def _is_done(self, ticket_id: str, cache: dict[str, bool]) -> bool:
        if ticket_id not in cache:
            cache[ticket_id] = self.pm.get(ticket_id).status == "done"
        return cache[ticket_id]

    def _guard(self, t: Ticket, fn) -> None:
        try:
            fn(t)
        except Blocked as e:
            self.pm.set_status(t.id, "blocked")
            self.pm.comment(
                t.id,
                f"⛔ **I'm blocked and need a human.**\n\n{e}\n\nReply on this ticket and I'll pick it up again.",
                self.sig,
            )
            self.journal.log(t.id, "blocked", str(e).splitlines()[0][:200])
        except Exception as e:  # infra failure: park the ticket, keep the loop alive
            self.pm.set_status(t.id, "blocked")
            self.pm.comment(
                t.id, f"⚠️ Internal error while working on this ticket:\n```\n{str(e)[-1500:]}\n```", self.sig
            )
            self.journal.log(t.id, "error", f"{type(e).__name__}: {str(e)[:200]}")

    def _account(self, t: Ticket, phase: str, res: AgentResult, msg: str) -> None:
        self.journal.log(t.id, phase, msg, res.cost_usd, res.duration_s, res.log_path)

    # ============================================================ planning
    def plan(self, t: Ticket) -> None:
        self.pm.set_status(t.id, "in-progress")
        self.pm.comment(
            t.id, "👋 I've picked this up. Researching the codebase, wiki and data before planning.", self.sig
        )
        self.journal.log(t.id, "intake", f"[{t.type}] {t.title}")
        repo = self.cfg.repo(None)
        ws = Workspace(self.cfg, repo)
        ws.prepare(repo.default_branch)
        repos = "\n".join(f"- {r.name} ({r.github})" for r in self.cfg.repos)
        res = self.brain.think(
            plan_prompt(t.context_markdown(), repos, self.cfg.policy.max_tasks_per_epic),
            PLAN_SCHEMA,
            ws.path,
            f"plan-{t.id}",
        )
        self._account(t, "plan", res, f"planned: {len(res.data.get('tasks', []))} tasks" if res.ok else "failed")
        if not res.ok:
            raise RuntimeError(f"planning failed: {res.error}")
        plan = res.data
        if not plan["sufficient"] or not plan["tasks"]:
            qs = "\n".join(f"{i}. {q}" for i, q in enumerate(plan["questions"], 1))
            raise Blocked(
                f"I researched this but can't plan it responsibly yet.\n\n**My understanding:** "
                f"{plan['understanding']}\n\n**Questions:**\n{qs}\n\n<details><summary>Research "
                f"notes</summary>\n\n{plan['research_notes']}\n</details>"
            )

        created: list[Ticket] = []
        for i, task in enumerate(plan["tasks"]):
            deps = [created[d].id for d in task.get("depends_on", []) if 0 <= d < i]
            ac = "\n".join(f"- [ ] {c}" for c in task["acceptance_criteria"])
            body = f"{task['description']}\n\n**Acceptance criteria**\n{ac}\n\nPart of #{t.id}" + (
                f" · Depends on {', '.join('#' + d for d in deps)}" if deps else ""
            )
            child = self.pm.create(
                "task",
                task["title"],
                body,
                parent=t.id,
                meta={"depends_on": deps, "repo": task.get("repo") or repo.name},
            )
            created.append(child)
            self.journal.log(t.id, "task", f"created #{child.id}: {child.title}", link=child.url)

        tasks_md = "\n".join(f"{i}. #{c.id} {c.title}" for i, c in enumerate(created, 1))
        self.pm.comment(
            t.id,
            f"📋 **Plan**\n\n{plan['understanding']}\n\n**Tasks** (each ships as its own PR):\n"
            f"{tasks_md}\n\n**Research notes**\n\n{plan['research_notes']}",
            self.sig,
        )
        self.pm.mark_planned(t.id)

    # =========================================================== execution
    def _checks_md(self, repo: RepoConfig) -> str:
        return "\n".join(f"  - `{c}`" for c in repo.checks) or "  - (no checks configured)"

    def execute(self, t: Ticket) -> None:
        repo = self.cfg.repo(t.repo)
        branch = f"deleg8/{t.id}-{slugify(t.title)}"
        self.pm.set_status(t.id, "in-progress")
        self.pm.comment(t.id, f"🛠️ Starting work on branch `{branch}` in `{repo.github}`.", self.sig)
        self.journal.log(t.id, "start", f"{t.title} -> {branch}")
        ws = Workspace(self.cfg, repo)
        ws.prepare(branch)

        parent_md = self.pm.get(t.parent).context_markdown(max_comments=3) if t.parent else ""
        res = self.coder.work(
            work_prompt(t.context_markdown(), parent_md, self._checks_md(repo)),
            WORK_SCHEMA,
            ws.path,
            f"work-{t.id}",
        )
        self._account(t, "code", res, res.data.get("commit_message", res.error[:120]))
        if not res.ok:
            raise RuntimeError(f"coding harness failed: {res.error}")
        result = res.data
        if result["status"] == "blocked":
            qs = "\n".join(f"- {q}" for q in result["questions"])
            raise Blocked(f"{result['summary']}\n\n**Questions:**\n{qs}")

        result = self._until_checks_pass(t, ws, result)
        if not ws.has_changes() and ws.git("rev-list", "--count", f"origin/{repo.default_branch}..HEAD") == "0":
            if result.get("ticket_notes"):  # research-only task: deliverable is the answer itself
                self.pm.comment(
                    t.id,
                    f"✅ Done (no code change needed).\n\n{result['summary']}\n\n{result['ticket_notes']}",
                    self.sig,
                )
                self.pm.set_status(t.id, "done")
                return
            raise Blocked(
                f"I finished without changing any code, which probably means I misunderstood "
                f"the ticket.\n\n{result['summary']}"
            )

        subject = re.sub(rf"\s*\(#{t.id}\)\s*$", "", result["commit_message"].strip())
        message = f"{subject} (#{t.id})"
        ws.commit_and_push(branch, message)
        prs = GitHubPRs(repo)
        pr = prs.open(branch, message, self._pr_body(t, result, ws))
        self.pm.set_status(t.id, "in-review")
        self.pm.comment(t.id, f"🔀 Opened PR {pr['url']}. Next: AI code review, then CI.", self.sig)
        files = ws.changed_files()
        self.journal.log(t.id, "pr", f"opened PR #{pr['number']} ({len(files)} files)", link=pr["url"])
        self.journal.log(t.id, "files", ", ".join(files)[:500])
        self._review_ci_merge(t, ws, prs, pr, result)

    def _until_checks_pass(self, t: Ticket, ws: Workspace, result: dict) -> dict:
        for attempt in range(self.cfg.policy.max_fix_attempts + 1):
            ok, output = ws.run_checks()
            self.journal.log(t.id, "checks", "local checks passed" if ok else f"local checks failed (#{attempt + 1})")
            if ok:
                return result
            if attempt == self.cfg.policy.max_fix_attempts:
                break
            res = self.coder.work(
                fix_prompt("the project checks fail", f"```\n{output[-6000:]}\n```"),
                WORK_SCHEMA,
                ws.path,
                f"fix-{t.id}",
            )
            self._account(t, "fix", res, "fixing local checks")
            if res.ok:
                result = {
                    **result,
                    **res.data,
                    "ticket_notes": res.data.get("ticket_notes") or result.get("ticket_notes", ""),
                }
        raise Blocked(
            f"Local checks still fail after {self.cfg.policy.max_fix_attempts} fix attempts:\n"
            f"```\n{output[-2500:]}\n```"
        )

    def _pr_body(self, t: Ticket, result: dict, ws: Workspace) -> str:
        notes = f"\n\n### Notes for the ticket\n{result['ticket_notes']}" if result.get("ticket_notes") else ""
        return (
            f"Closes #{t.id}\n\n### What & why\n{result['summary']}\n\n### Verification\n{result['tests']}"
            f"{notes}\n\n```\n{ws.diffstat_vs_base()}\n```\n\n---\n{self.sig}"
        )

    def _review_ci_merge(
        self, t: Ticket, ws: Workspace, prs: GitHubPRs, pr: dict, result: dict, skip_review: bool = False
    ) -> None:
        policy, n, branch = self.cfg.policy, pr["number"], ws.git("rev-parse", "--abbrev-ref", "HEAD")

        # ---- AI code review (a separate model run acts as the senior reviewer)
        if policy.ai_review and not skip_review:
            for rnd in range(policy.max_review_rounds + 1):
                _, checks = ws.run_checks()
                rv = self.brain.think(
                    review_prompt(t.context_markdown(), ws.diff_vs_base(), checks[-3000:]),
                    REVIEW_SCHEMA,
                    ws.path,
                    f"review-{t.id}",
                )
                self._account(t, "review", rv, rv.data.get("verdict", "review failed"))
                if not rv.ok:
                    break
                issues = (
                    "\n".join(f"- **{i['severity']}** {i.get('file', '')}: {i['comment']}" for i in rv.data["issues"])
                    or "- none"
                )
                icon = "✅" if rv.data["verdict"] == "approve" else "🔁"
                prs.comment(
                    n,
                    f"### {icon} AI code review: `{rv.data['verdict']}`\n\n{rv.data['summary']}\n\n"
                    f"{issues}\n\n---\n🧑‍⚖️ deleg8 reviewer",
                )
                if rv.data["verdict"] == "approve":
                    break
                if rnd == policy.max_review_rounds:
                    self.pm.comment(
                        t.id,
                        f"The reviewer still has concerns after {rnd} rounds. Leaving "
                        f"PR {pr['url']} for a human reviewer.",
                        self.sig,
                    )
                    return
                fx = self.coder.work(
                    fix_prompt("the code reviewer requested changes", issues),
                    WORK_SCHEMA,
                    ws.path,
                    f"review-fix-{t.id}",
                )
                self._account(t, "fix", fx, "addressing review comments")
                self._until_checks_pass(t, ws, result)
                ws.commit_and_push(branch, f"fix: address review feedback (#{t.id})")

        # ---- CI
        if policy.wait_for_ci:
            for attempt in range(policy.max_fix_attempts + 1):
                cr = prs.wait_for_checks(n, policy.ci_timeout_s)
                self.journal.log(t.id, "ci", f"{cr.state}: {cr.summary}")
                if cr.state in ("pass", "none"):
                    break
                if cr.state == "pending":
                    raise Blocked(f"CI did not finish within {policy.ci_timeout_s}s on {pr['url']}.")
                if attempt == policy.max_fix_attempts:
                    raise Blocked(
                        f"CI is still failing on {pr['url']} after {attempt} fixes.\n```\n{cr.failed_logs[-2500:]}\n```"
                    )
                fx = self.coder.work(
                    fix_prompt("CI failed on the pull request", f"```\n{cr.failed_logs}\n```"),
                    WORK_SCHEMA,
                    ws.path,
                    f"ci-fix-{t.id}",
                )
                self._account(t, "fix", fx, "fixing CI failure")
                self._until_checks_pass(t, ws, result)
                ws.commit_and_push(branch, f"fix: make CI green (#{t.id})")

        # ---- merge (or hand over to a human, per policy)
        if not policy.auto_merge:
            self.pm.comment(
                t.id,
                f"👀 PR {pr['url']} is green and AI-reviewed. Waiting for a human to approve and merge.",
                self.sig,
            )
            self.journal.log(t.id, "handoff", "awaiting human merge", link=pr["url"])
            return
        prs.merge(n)
        self._complete(t, pr, result, ws.repo)

    def _complete(self, t: Ticket, pr: dict, result: dict, repo: RepoConfig) -> None:
        self.pm.set_status(t.id, "done")
        cost, secs, first, last = self.journal.totals([t.id])
        notes = f"\n\n**Requested info**\n{result['ticket_notes']}" if result.get("ticket_notes") else ""
        deploy = f"\n\n🚀 Deploying to {repo.deploy_url} via GitHub Actions." if repo.deploy_url else ""
        self.pm.comment(
            t.id,
            f"✅ **Done.** Merged {pr['url']}.\n\n{result['summary']}{notes}{deploy}\n\n"
            f"<sub>AI time {secs / 60:.1f} min · cost ${cost:.2f}</sub>",
            self.sig,
        )
        self.journal.log(t.id, "done", "merged and closed", link=pr["url"])

    def resume_review(self, t: Ticket) -> None:
        repo = self.cfg.repo(t.repo)
        branch = f"deleg8/{t.id}-{slugify(t.title)}"
        prs = GitHubPRs(repo)
        pr = prs.find(branch)
        if not pr:
            self.pm.set_status(t.id, "todo")
            return
        if pr["state"] == "MERGED":
            self._complete(t, pr, {"summary": "Merged by a human reviewer."}, repo)
        elif pr["state"] == "CLOSED":
            raise Blocked(f"PR {pr['url']} was closed without merging. Should I try a different approach?")
        elif self.cfg.policy.auto_merge:
            ws = Workspace(self.cfg, repo)
            ws.prepare(branch)
            self._review_ci_merge(t, ws, prs, pr, {"summary": "Resumed after interruption."}, skip_review=True)

    # =========================================================== reporting
    def finalize(self, t: Ticket, kids: list[Ticket]) -> None:
        ids = [t.id] + [k.id for k in kids]
        cost, secs, first, last = self.journal.totals(ids)
        stats = (
            f"- tasks: {len(kids)}\n- AI agent time: {secs / 60:.1f} min\n- wall-clock: "
            f"{(last - first) / 60:.1f} min\n- model cost: ${cost:.2f}"
        )
        kids_md = "\n\n".join(
            f"### #{k.id} {k.title}\n{k.url}\nEvidence trail (harness journal):\n"
            + "\n".join(f"- {line}" for line in self.journal.trail(k.id))
            + "\n\nCompletion note:\n"
            + next((c.body for c in reversed(k.comments) if c.by_agent and "Done" in c.body), "")[:2000]
            for k in kids
        )
        deploys = []
        for repo in self.cfg.repos:
            run_ = GitHubPRs(repo).latest_deploy() if repo.deploy_url else None
            if run_:
                deploys.append(
                    f"- {repo.name}: latest deploy run {run_.get('status')}/{run_.get('conclusion')} "
                    f"{run_.get('url')} -> {repo.deploy_url}"
                )
        if deploys:
            stats += "\n" + "\n".join(deploys)
        res = self.brain.think(
            report_prompt(t.context_markdown(max_comments=4), kids_md, stats),
            REPORT_SCHEMA,
            self.cfg.root,
            f"report-{t.id}",
        )
        self._account(t, "report", res, "completion report")
        report = res.data.get("report") if res.ok else f"All {len(kids)} tasks are done."
        report_md = f"# {t.title}\n\n{report}\n\n---\n**Stats**\n{stats}\n"
        out = self.cfg.state_dir / "reports"
        out.mkdir(exist_ok=True)
        (out / f"{t.id}-{slugify(t.title)}.md").write_text(
            f"<!-- generated {datetime.now().isoformat(timespec='seconds')} -->\n{report_md}"
        )
        self.pm.comment(t.id, f"🏁 **Completion report**\n\n{report}\n\n---\n**Stats**\n{stats}", self.sig)
        self.pm.set_status(t.id, "done")
        self.journal.log(t.id, "complete", f"{t.type} done: {len(kids)} tasks, ${cost:.2f}")
