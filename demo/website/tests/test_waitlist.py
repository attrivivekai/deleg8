def test_signup_via_api(client):
    res = client.post("/api/waitlist", json={"email": "Ada@Example.com", "company": "Acme"})
    assert res.status_code == 201
    assert res.json()["email"] == "ada@example.com"
    assert client.get("/api/waitlist/count").json() == {"count": 1}


def test_signup_via_form_redirects(client):
    res = client.post(
        "/waitlist",
        data={"email": "grace@example.com", "plan_interest": "team"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"].endswith("/thanks")


def test_rejects_missing_at_sign(client):
    res = client.post("/api/waitlist", json={"email": "not-an-email"})
    assert res.status_code == 422


def test_rejects_unknown_plan(client):
    res = client.post("/api/waitlist", json={"email": "a@b.co", "plan_interest": "gold"})
    assert res.status_code == 422
