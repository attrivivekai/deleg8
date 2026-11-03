"""End-to-end workflow tests of the employee state machine with fake PM / harness / git / CI."""

from fakes import FakePM, FakePRs, FakeWorkspace, ScriptedHarness

from deleg8.employee import Employee
from deleg8.scm import CheckResult

PLAN = {
    "understanding": "Add a changelog page",
    "research_notes": "Read wiki timeline",
    "sufficient": True,
    "questions": [],
    "tasks": [
        {"title": "Changelog data", "description": "d", "acceptance_criteria": ["a"], "depends_on": []},
        {"title": "Changelog page", "description": "d", "acceptance_criteria": ["b"], "depends_on": [0]},
    ],
}
WORK = {
    "status": "done",
    "summary": "did it",
    "commit_message": "feat: x",
    "tests": "pytest ok",
    "ticket_notes": "",
    "questions": [],
}
APPROVE = {"verdict": "approve", "summary": "lgtm", "issues": []}
REPORT = {"report": "All shipped."}


def make(cfg, journal, brain_responses, work=None):
    pm = FakePM()

    def on_work(tag):
        for ws in FakeWorkspace.instances:
            ws.changed = True

    coder = ScriptedHarness(
        {"work": [work or WORK], "fix": [WORK], "review-fix": [WORK], "ci-fix": [WORK]}, on_work=on_work
    )
    brain = ScriptedHarness(brain_responses)
    return pm, Employee(cfg, pm=pm, coder=coder, brain=brain, journal=journal), coder, brain


def drain(emp, passes=6):
    for _ in range(passes):
        if not emp.run_once():
            return


def test_epic_is_planned_executed_in_order_and_reported(cfg, fakes):
    pm, emp, coder, brain = make(cfg, fakes, {"plan": [PLAN], "review": [APPROVE], "report": [REPORT]})
    epic = pm.add("epic", "Public changelog")

    emp.run_once()
    kids = pm.children(epic.id)
    assert [k.title for k in kids] == ["Changelog data", "Changelog page"]
    assert kids[1].depends_on == [kids[0].id]
    assert pm.get(epic.id).planned

    drain(emp)
    assert all(k.status == "done" for k in pm.children(epic.id))
    assert pm.get(epic.id).status == "done"
    assert "Completion report" in pm.get(epic.id).comments[-1].body
    assert FakePRs.merged == [7, 7]
    order = [tag for kind, tag in coder.calls if kind == "work"]
    assert order == [f"work-{kids[0].id}", f"work-{kids[1].id}"]  # dependency respected
    assert (cfg.state_dir / "reports").exists()


def test_vague_ticket_blocks_with_questions_then_resumes_after_reply(cfg, fakes):
    vague = {**PLAN, "sufficient": False, "tasks": [], "questions": ["Which pages?", "What metric?"]}
    pm, emp, _, _ = make(cfg, fakes, {"plan": [vague, PLAN], "review": [APPROVE], "report": [REPORT]})
    story = pm.add("story", "Make it better for enterprise")

    emp.run_once()
    t = pm.get(story.id)
    assert t.status == "blocked"
    assert "Which pages?" in t.comments[-1].body

    emp.run_once()  # nobody answered: stays blocked, no new work
    assert pm.get(story.id).status == "blocked" and not pm.children(story.id)

    pm.human_comment(story.id, "Focus on pricing; metric is demo requests.")
    drain(emp)
    assert pm.get(story.id).status == "done"


def test_bug_with_failing_ci_gets_fixed_then_merged(cfg, fakes):
    pm, emp, coder, _ = make(cfg, fakes, {"review": [APPROVE]})
    bug = pm.add("bug", "Email validation")
    FakePRs.ci_results = [CheckResult("fail", "test=fail", "AssertionError"), CheckResult("pass", "test=pass")]

    emp.run_once()
    assert pm.get(bug.id).status == "done"
    assert any(kind == "ci-fix" for kind, _ in coder.calls)
    assert "make CI green" in FakeWorkspace.instances[-1].pushed[-1]


def test_review_requested_changes_are_addressed(cfg, fakes):
    changes = {
        "verdict": "request_changes",
        "summary": "missing test",
        "issues": [{"severity": "major", "comment": "add a test"}],
    }
    pm, emp, coder, _ = make(cfg, fakes, {"review": [changes, APPROVE]})
    bug = pm.add("bug", "Thing")
    emp.run_once()
    assert any(kind == "review-fix" for kind, _ in coder.calls)
    assert pm.get(bug.id).status == "done"


def test_persistent_local_check_failure_blocks_ticket(cfg, fakes):
    pm, emp, _, _ = make(cfg, fakes, {"review": [APPROVE]})
    FakeWorkspace.checks_ok = False
    bug = pm.add("bug", "Broken")
    emp.run_once()
    assert pm.get(bug.id).status == "blocked"
    assert "Local checks still fail" in pm.get(bug.id).comments[-1].body
    assert FakePRs.merged == []


def test_agent_reporting_blocked_escalates(cfg, fakes):
    blocked = {**WORK, "status": "blocked", "questions": ["Which DB?"]}
    pm, emp, _, _ = make(cfg, fakes, {}, work=blocked)
    t = pm.add("task", "Ambiguous")
    emp.run_once()
    assert pm.get(t.id).status == "blocked"
    assert "Which DB?" in pm.get(t.id).comments[-1].body


def test_no_auto_merge_hands_off_to_human(cfg, fakes):
    cfg.policy.auto_merge = False
    pm, emp, _, _ = make(cfg, fakes, {"review": [APPROVE]})
    t = pm.add("task", "Small change")
    emp.run_once()
    assert FakePRs.merged == []
    assert "Waiting for a human" in pm.get(t.id).comments[-1].body


def test_commit_message_ticket_suffix_not_duplicated(cfg, fakes):
    work = {**WORK, "commit_message": "feat: thing (#1)"}
    pm, emp, _, _ = make(cfg, fakes, {"review": [APPROVE]}, work=work)
    pm.add("task", "Thing")
    emp.run_once()
    assert FakeWorkspace.instances[-1].pushed[0] == "feat: thing (#1)"
