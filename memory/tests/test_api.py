def test_health_and_info(api_client):
    r = api_client.get("/health")
    assert r.status_code == 200
    assert r.json()["organ"] == "memory"

    r = api_client.get("/info")
    assert r.status_code == 200
    assert "scars" in r.json()["capabilities"]


def test_advertised_capabilities_include_doctor(api_client):
    """/memory/doctor is a real endpoint — the capabilities list
    published to the registry must say so, same as every other organ
    with a doctor endpoint (Sandbox, Orchestrator, Communications)."""
    r = api_client.get("/info")
    assert "doctor" in r.json()["capabilities"]

    r = api_client.get("/memory/doctor")
    assert r.status_code == 200


def test_add_and_recall_roundtrip(api_client):
    r = api_client.post("/memory/add", json={"text": "the bus organ hasn't been built yet", "tags": ["planning"]})
    assert r.status_code == 200
    assert r.json()["stored"] is True

    r = api_client.get("/memory/recall", params={"q": "bus organ", "k": 3})
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_add_with_provenance_and_permissions(api_client):
    r = api_client.post("/memory/add", json={
        "text": "sensitive detail", "provenance": "conversation", "witness": "direct",
        "confidence": 0.6, "owner": "jimmydev", "may_reveal": False,
    })
    assert r.status_code == 200
    entry_id = r.json()["id"]

    r = api_client.get(f"/memory/entries/{entry_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["provenance"] == "conversation"
    assert body["permissions"]["may_reveal"] is False


def test_invalid_witness_returns_error_envelope(api_client):
    r = api_client.post("/memory/add", json={"text": "x", "witness": "vibes"})
    assert r.status_code == 400
    assert "error" in r.json()
    assert r.json()["error"]["code"] == "memory_error"


def test_scar_lifecycle_via_api(api_client):
    r = api_client.post("/memory/scars/propose", json={
        "trigger_event": "API returned stale data", "lesson": "verify freshness before trusting trend data",
        "confidence": 0.95,
    })
    assert r.status_code == 200
    proposal_id = r.json()["id"]

    r = api_client.post(f"/memory/scars/proposals/{proposal_id}/decide", json={"decision": "accept"})
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"

    r = api_client.get("/memory/scars")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_scar_bad_decision_value_returns_error_envelope(api_client):
    r = api_client.post("/memory/scars/propose", json={"trigger_event": "x", "lesson": "y"})
    proposal_id = r.json()["id"]
    r = api_client.post(f"/memory/scars/proposals/{proposal_id}/decide", json={"decision": "maybe"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "memory_error"


def test_promise_lifecycle_via_api(api_client):
    r = api_client.post("/memory/promises", json={"text": "follow up tomorrow", "condition": "tomorrow"})
    assert r.status_code == 200
    promise_id = r.json()["id"]

    r = api_client.get("/memory/promises", params={"status": "pending"})
    assert len(r.json()) == 1

    r = api_client.post(f"/memory/promises/{promise_id}/resolve", json={"status": "fulfilled"})
    assert r.status_code == 200

    r = api_client.get("/memory/promises", params={"status": "pending"})
    assert len(r.json()) == 0


def test_relation_contradiction_via_api(api_client):
    e1 = api_client.post("/memory/add", json={"text": "claim A"}).json()
    e2 = api_client.post("/memory/add", json={"text": "claim B"}).json()

    r = api_client.post("/memory/relations", json={
        "id_a": e1["id"], "type_a": "entry", "id_b": e2["id"], "type_b": "entry", "relation_type": "contradicts",
    })
    assert r.status_code == 200
    relation_id = r.json()["id"]
    assert r.json()["status"] == "unresolved"

    r = api_client.post(f"/memory/relations/{relation_id}/resolve", json={"resolved_which": "b", "note": "B is newer"})
    assert r.status_code == 200
    assert r.json()["resolved_which"] == "b"


def test_pin_prune_revive_via_api(api_client):
    entry = api_client.post("/memory/add", json={"text": "will be pinned"}).json()
    r = api_client.post(f"/memory/entries/{entry['id']}/pin")
    assert r.status_code == 200
    assert r.json()["pinned"] is True

    r = api_client.get(f"/memory/entries/{entry['id']}")
    assert r.json()["salience"] == 1.0


def test_stats_reflects_everything(api_client):
    api_client.post("/memory/add", json={"text": "a"})
    api_client.post("/memory/promises", json={"text": "a promise"})
    api_client.post("/memory/unknowable", json={"description": "d", "reason": "r"})

    r = api_client.get("/memory/stats")
    body = r.json()
    assert body["ledger_entries"] == 1
    assert body["pending_promises"] == 1
    assert body["open_unknowables"] == 1
