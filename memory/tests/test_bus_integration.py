"""
test_bus_integration.py — proves two things:
  1. When Communications IS reachable, Memory publishes the right event
     for each permanent state change (fact accepted, scar accepted,
     promise/unknowable/relation resolved).
  2. When it's NOT reachable (the normal case in every other test file,
     since no registry runs in tests), Memory operations still succeed —
     the bus is decoration, never a dependency.
"""
import importlib


def test_decide_proposal_accept_publishes_fact_added(api_client, monkeypatch):
    import main
    published = []
    monkeypatch.setattr(main, "_publish_event", lambda topic, event_type, payload: published.append((topic, event_type, payload)))

    for _ in range(3):
        api_client.post("/memory/add", json={"text": "always back up before migration"})
    api_client.post("/memory/consolidate", json={"threshold": 0.80, "min_witnesses": 3})
    proposal = api_client.get("/memory/proposals").json()[0]

    api_client.post(f"/memory/proposals/{proposal['id']}/decide", json={"decision": "accept"})

    assert len(published) == 1
    topic, event_type, payload = published[0]
    assert topic == "memory.facts"
    assert event_type == "fact_added"
    assert "source_ids" in payload


def test_decide_proposal_skip_does_not_publish(api_client, monkeypatch):
    import main
    published = []
    monkeypatch.setattr(main, "_publish_event", lambda *a: published.append(a))

    for _ in range(3):
        api_client.post("/memory/add", json={"text": "this one gets skipped"})
    api_client.post("/memory/consolidate", json={"threshold": 0.80, "min_witnesses": 3})
    proposal = api_client.get("/memory/proposals").json()[0]

    api_client.post(f"/memory/proposals/{proposal['id']}/decide", json={"decision": "skip"})
    assert published == []


def test_decide_scar_accept_publishes_scar_added(api_client, monkeypatch):
    import main
    published = []
    monkeypatch.setattr(main, "_publish_event", lambda topic, event_type, payload: published.append((topic, event_type, payload)))

    r = api_client.post("/memory/scars/propose", json={"trigger_event": "x", "lesson": "y"})
    api_client.post(f"/memory/scars/proposals/{r.json()['id']}/decide", json={"decision": "accept"})

    assert len(published) == 1
    topic, event_type, payload = published[0]
    assert topic == "memory.scars"
    assert event_type == "scar_added"


def test_decide_scar_supersede_publishes_scar_superseded(api_client, monkeypatch):
    import main
    published = []
    monkeypatch.setattr(main, "_publish_event", lambda topic, event_type, payload: published.append((topic, event_type, payload)))

    r1 = api_client.post("/memory/scars/propose", json={"trigger_event": "a", "lesson": "v1"})
    old_id = api_client.post(f"/memory/scars/proposals/{r1.json()['id']}/decide", json={"decision": "accept"}).json()["scar_id"]

    r2 = api_client.post("/memory/scars/propose", json={"trigger_event": "b", "lesson": "v2", "supersedes": old_id})
    api_client.post(f"/memory/scars/proposals/{r2.json()['id']}/decide", json={"decision": "accept"})

    event_types = [e[1] for e in published]
    assert event_types == ["scar_added", "scar_superseded"]


def test_resolve_promise_publishes_event(api_client, monkeypatch):
    import main
    published = []
    monkeypatch.setattr(main, "_publish_event", lambda topic, event_type, payload: published.append((topic, event_type, payload)))

    p = api_client.post("/memory/promises", json={"text": "follow up"}).json()
    api_client.post(f"/memory/promises/{p['id']}/resolve", json={"status": "fulfilled"})

    assert len(published) == 1
    topic, event_type, payload = published[0]
    assert topic == "memory.promises"
    assert payload["status"] == "fulfilled"


def test_resolve_unknowable_publishes_event(api_client, monkeypatch):
    import main
    published = []
    monkeypatch.setattr(main, "_publish_event", lambda topic, event_type, payload: published.append((topic, event_type, payload)))

    entry = api_client.post("/memory/add", json={"text": "the answer was X"}).json()
    u = api_client.post("/memory/unknowable", json={"description": "mystery", "reason": "under NDA"}).json()
    api_client.post(f"/memory/unknowable/{u['id']}/resolve", json={"resolved_entry_id": entry["id"]})

    assert len(published) == 1
    assert published[0][0] == "memory.unknowable"


def test_resolve_relation_publishes_event(api_client, monkeypatch):
    import main
    published = []
    monkeypatch.setattr(main, "_publish_event", lambda topic, event_type, payload: published.append((topic, event_type, payload)))

    e1 = api_client.post("/memory/add", json={"text": "claim A"}).json()
    e2 = api_client.post("/memory/add", json={"text": "claim B"}).json()
    rel = api_client.post("/memory/relations", json={
        "id_a": e1["id"], "type_a": "entry", "id_b": e2["id"], "type_b": "entry", "relation_type": "contradicts",
    }).json()

    api_client.post(f"/memory/relations/{rel['id']}/resolve", json={"resolved_which": "b"})

    assert len(published) == 1
    assert published[0][0] == "memory.relations"
    assert published[0][2]["resolved_which"] == "b"


def test_relates_to_never_publishes_since_it_never_resolves_via_endpoint(api_client, monkeypatch):
    """relates_to auto-resolves at creation time, not through the
    resolve endpoint — so it should never trigger a publish."""
    import main
    published = []
    monkeypatch.setattr(main, "_publish_event", lambda *a: published.append(a))

    e1 = api_client.post("/memory/add", json={"text": "a"}).json()
    e2 = api_client.post("/memory/add", json={"text": "b"}).json()
    api_client.post("/memory/relations", json={
        "id_a": e1["id"], "type_a": "entry", "id_b": e2["id"], "type_b": "entry", "relation_type": "relates_to",
    })
    assert published == []


def test_operations_succeed_even_when_communications_is_unreachable(api_client):
    """The real integration test: NO mocking, NO registry running in this
    test environment at all — discover() will genuinely fail. Every
    write operation must still return success. This is the same
    guarantee every other test file in this suite has been proving
    implicitly all along; this test just makes it explicit."""
    r = api_client.post("/memory/scars/propose", json={"trigger_event": "x", "lesson": "y"})
    proposal_id = r.json()["id"]
    r = api_client.post(f"/memory/scars/proposals/{proposal_id}/decide", json={"decision": "accept"})
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"

    p = api_client.post("/memory/promises", json={"text": "x"}).json()
    r = api_client.post(f"/memory/promises/{p['id']}/resolve", json={"status": "fulfilled"})
    assert r.status_code == 200
