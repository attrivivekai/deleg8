"""CircleCI support: fetch the failing step's log for a CircleCI check on a pull request.

CircleCI reports results to GitHub as commit statuses/checks, so `gh pr checks` already sees them (pass/fail).
This module only adds *why*: with CIRCLE_TOKEN set (CircleCI -> User settings -> Personal API tokens), the
failing step output is fetched via the v1.1 API so the coding agent can fix CI breaks like with GitHub Actions.
"""

from __future__ import annotations

import os
import re

import httpx

API = "https://circleci.com/api/v1.1/project"
JOB_URL_PATTERNS = [
    # https://app.circleci.com/pipelines/github/OWNER/REPO/12/workflows/<uuid>/jobs/34
    re.compile(
        r"app\.circleci\.com/pipelines/(?P<vcs>github|gh|bitbucket|bb)/(?P<owner>[^/]+)/(?P<repo>[^/]+)/"
        r"\d+/workflows/[^/]+/jobs/(?P<job>\d+)"
    ),
    # https://circleci.com/gh/OWNER/REPO/34
    re.compile(r"circleci\.com/(?P<vcs>gh|github|bb|bitbucket)/(?P<owner>[^/]+)/(?P<repo>[^/?#]+)/(?P<job>\d+)"),
]
VCS = {"gh": "github", "github": "github", "bb": "bitbucket", "bitbucket": "bitbucket"}


def is_circleci(link: str) -> bool:
    return "circleci.com" in (link or "")


def parse_job_url(link: str) -> tuple[str, str, str, int] | None:
    for pattern in JOB_URL_PATTERNS:
        if m := pattern.search(link or ""):
            return VCS[m["vcs"]], m["owner"], m["repo"], int(m["job"])
    return None


def failed_step_log(
    link: str, token: str | None = None, client: httpx.Client | None = None, max_chars: int = 6000
) -> str:
    token = token or os.environ.get("CIRCLE_TOKEN") or os.environ.get("CIRCLECI_TOKEN")
    if not token:
        return f"(set CIRCLE_TOKEN so deleg8 can fetch CircleCI logs; failing job: {link})"
    parsed = parse_job_url(link)
    if not parsed:
        return f"(unrecognized CircleCI job URL: {link})"
    vcs, owner, repo, job = parsed
    http = client or httpx.Client(timeout=30)
    r = http.get(f"{API}/{vcs}/{owner}/{repo}/{job}", headers={"Circle-Token": token})
    r.raise_for_status()
    out = []
    for step in r.json().get("steps", []):
        for action in step.get("actions", []):
            if action.get("failed") or action.get("status") in ("failed", "timedout"):
                text = ""
                if action.get("output_url"):
                    msgs = http.get(action["output_url"]).json()
                    text = "".join(m.get("message", "") for m in msgs)
                out.append(f"--- step: {action.get('name', step.get('name'))} (exit {action.get('exit_code')})\n{text}")
    return ("\n".join(out) or f"(no failed step found in {link})")[-max_chars:]
