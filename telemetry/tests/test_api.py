def test_health_and_info(api_client):
    r = api_client.get("/health")
    assert r.status_code == 200
    r = api_client.get("/info")
    assert "emit" in r.json()["capabilities"]


def test_emit_via_api(api_client):
    r = api_client.post("/telemetry/events", json={
        "event_type": "request", "source": "io_interface", "payload": {"text": "memory stats"},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "io_interface"
    assert body["event_id"]


def test_emit_invalid_status_returns_error_envelope(api_client):
    r = api_client.post("/telemetry/events", json={
        "event_type": "request", "source": "memory", "status": "not_a_status",
    })
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "telemetry_error"


def test_query_via_api(api_client):
    api_client.post("/telemetry/events", json={"event_type": "request", "source": "memory"})
    api_client.post("/telemetry/events", json={"event_type": "request", "source": "sandbox"})

    r = api_client.get("/telemetry/events", params={"source": "sandbox"})
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["source"] == "sandbox"


def test_get_event_via_api(api_client):
    event = api_client.post("/telemetry/events", json={
        "event_type": "request", "source": "memory",
    }).json()

    r = api_client.get(f"/telemetry/events/{event['event_id']}")
    assert r.status_code == 200
    assert r.json()["event_id"] == event["event_id"]


def test_get_missing_event_returns_error_envelope(api_client):
    r = api_client.get("/telemetry/events/does-not-exist")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "telemetry_error"


def test_recent_via_api(api_client):
    for _ in range(3):
        api_client.post("/telemetry/events", json={"event_type": "request", "source": "memory"})
    r = api_client.get("/telemetry/recent", params={"limit": 2})
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_timeline_via_api(api_client):
    api_client.post("/telemetry/events", json={
        "event_type": "request", "source": "io_interface", "correlation_id": "ABC123",
    })
    api_client.post("/telemetry/events", json={
        "event_type": "decision", "source": "critic", "correlation_id": "ABC123",
    })
    r = api_client.get("/telemetry/timeline", params={"correlation_id": "ABC123"})
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert body[0]["source"] == "io_interface"


def test_stats_via_api(api_client):
    api_client.post("/telemetry/events", json={"event_type": "request", "source": "memory"})
    r = api_client.get("/telemetry/stats")
    assert r.status_code == 200
    assert r.json()["total_events"] == 1
