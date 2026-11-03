import httpx

from deleg8 import circleci

APP_URL = "https://app.circleci.com/pipelines/github/acme/site/12/workflows/5f0c-1a/jobs/34"


def test_parse_job_urls():
    assert circleci.parse_job_url(APP_URL) == ("github", "acme", "site", 34)
    assert circleci.parse_job_url("https://circleci.com/gh/acme/site/77?utm=x") == ("github", "acme", "site", 77)
    assert circleci.parse_job_url("https://github.com/acme/site/actions/runs/1") is None


def test_failed_step_log_fetches_only_failing_steps():
    def handler(req: httpx.Request):
        if req.url.path == "/api/v1.1/project/github/acme/site/34":
            assert req.headers["Circle-Token"] == "tok"
            return httpx.Response(
                200,
                json={
                    "steps": [
                        {"name": "checkout", "actions": [{"name": "checkout", "status": "success", "output_url": "x"}]},
                        {
                            "name": "tests",
                            "actions": [
                                {
                                    "name": "uv run pytest -q",
                                    "failed": True,
                                    "exit_code": 1,
                                    "output_url": "https://logs.example/out",
                                }
                            ],
                        },
                    ]
                },
            )
        if req.url.host == "logs.example":
            return httpx.Response(200, json=[{"message": "FAILED tests/test_x.py::test_y - AssertionError\n"}])
        return httpx.Response(404)

    log = circleci.failed_step_log(APP_URL, token="tok", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert "uv run pytest -q (exit 1)" in log and "AssertionError" in log and "checkout" not in log


def test_without_token_points_to_job(monkeypatch):
    monkeypatch.delenv("CIRCLE_TOKEN", raising=False)
    monkeypatch.delenv("CIRCLECI_TOKEN", raising=False)
    assert "set CIRCLE_TOKEN" in circleci.failed_step_log(APP_URL)
