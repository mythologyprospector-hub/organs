def test_health_and_info(api_client):
    r = api_client.get("/health")
    assert r.status_code == 200
    r = api_client.get("/info")
    assert "handle" in r.json()["capabilities"]


def test_interpret_dry_run_via_api(api_client):
    r = api_client.post("/io/interpret", json={"text": "restart ollama"})
    assert r.status_code == 200
    body = r.json()
    assert body["matched"] is True
    assert body["intent"] == "orchestrator_restart"


def test_catalog_endpoint(api_client):
    r = api_client.get("/io/catalog")
    assert r.status_code == 200
    assert len(r.json()) > 0
    assert any(e["intent"] == "memory_add" for e in r.json())


def test_handle_with_no_registry_fails_closed_to_goal_creation(api_client):
    """No registry running in the test env — Critic is unreachable, so
    a risky-shaped request should fail closed and try (and fail) to
    create a goal, never silently execute."""
    r = api_client.post("/io/handle", json={"text": "restart ollama"})
    assert r.status_code == 200
    body = r.json()
    assert body["risk"]["requires_human_approval"] is True
    assert body["needs_approval"] is True


def test_handle_unmatched_text_via_api(api_client):
    r = api_client.post("/io/handle", json={"text": "do the quantum flibber thing"})
    assert r.status_code == 200
    assert r.json()["action_taken"] is False
    assert "examples" in r.json()
