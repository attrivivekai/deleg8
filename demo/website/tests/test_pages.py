import pytest


@pytest.mark.parametrize("path", ["/", "/how-it-works", "/pricing", "/thanks"])
def test_pages_render(client, path):
    res = client.get(path)
    assert res.status_code == 200
    assert "deleg" in res.text


def test_pricing_lists_all_plans(client):
    html = client.get("/pricing").text
    for name in ("Starter", "Team", "Enterprise"):
        assert name in html


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}
