def test_health_and_info(api_client):
    r = api_client.get("/health")
    assert r.status_code == 200
    r = api_client.get("/info")
    assert "enable" in r.json()["capabilities"]


def test_status_shows_disabled_by_default(api_client):
    r = api_client.get("/reflection/status")
    assert r.status_code == 200
    assert r.json()["enabled"] is False


def test_enable_disable_via_api(api_client):
    r = api_client.post("/reflection/enable")
    assert r.json()["enabled"] is True

    r = api_client.get("/reflection/status")
    assert r.json()["enabled"] is True

    r = api_client.post("/reflection/disable")
    assert r.json()["enabled"] is False


def test_configure_via_api(api_client):
    r = api_client.post("/reflection/configure", json={"interval_seconds": 120})
    assert r.status_code == 200
    assert r.json()["interval_seconds"] == 120


def test_configure_invalid_interval_returns_error_envelope(api_client):
    r = api_client.post("/reflection/configure", json={"interval_seconds": 1})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "reflection_error"


def test_manual_tick_without_memory_or_ollama_fails_cleanly(api_client):
    """No registry running in the test env — this proves the real
    failure path (memory unreachable) records cleanly instead of
    crashing the request."""
    r = api_client.post("/reflection/tick")
    assert r.status_code == 200
    body = r.json()
    assert body["ran"] is True
    assert body["success"] is False
    assert body["stage"] == "fetch_context"


def test_history_empty_initially(api_client):
    r = api_client.get("/reflection/history")
    assert r.status_code == 200
    assert r.json() == []


def test_history_populates_after_tick(api_client):
    api_client.post("/reflection/tick")
    r = api_client.get("/reflection/history")
    assert len(r.json()) == 1
