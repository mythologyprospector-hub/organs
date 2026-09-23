def test_health_and_info(api_client):
    r = api_client.get("/health")
    assert r.status_code == 200
    r = api_client.get("/info")
    assert "evaluate" in r.json()["capabilities"]


def test_evaluate_via_api(api_client):
    r = api_client.post("/critic/evaluate", json={"organ": "memory", "method": "GET", "path": "/memory/stats"})
    assert r.status_code == 200
    assert r.json()["risk_tier"] == "safe"


def test_unrecognized_action_via_api_fails_closed(api_client):
    r = api_client.post("/critic/evaluate", json={"organ": "x", "method": "POST", "path": "/nonsense"})
    assert r.status_code == 200
    assert r.json()["risk_tier"] == "high_risk"


def test_rules_endpoint(api_client):
    r = api_client.get("/critic/rules")
    assert r.status_code == 200
    assert len(r.json()) > 0
