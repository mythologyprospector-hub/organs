def test_health_and_info(api_client):
    r = api_client.get("/health")
    assert r.status_code == 200
    assert r.json()["organ"] == "communications"

    r = api_client.get("/info")
    assert "dispatch" in r.json()["capabilities"]


def test_advertised_capabilities_include_doctor(api_client):
    """/bus/doctor is a real endpoint — the capabilities list published
    to the registry must say so, same as every other organ with a
    doctor endpoint (Sandbox, Orchestrator, Memory)."""
    r = api_client.get("/info")
    assert "doctor" in r.json()["capabilities"]

    r = api_client.get("/bus/doctor")
    assert r.status_code == 200


def test_publish_and_consume_roundtrip(api_client):
    r = api_client.post("/bus/topics/memory.events/publish", json={
        "event_type": "fact_added", "payload": {"fact_id": 7}, "publisher": "memory",
    })
    assert r.status_code == 200
    assert r.json()["id"] == 1

    r = api_client.get("/bus/consume", params={"consumer": "watcher", "topics": "memory.events"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["events"][0]["payload"]["fact_id"] == 7


def test_consume_multiple_topics_comma_separated(api_client):
    api_client.post("/bus/topics/a/publish", json={"event_type": "e", "payload": {}, "publisher": "p"})
    api_client.post("/bus/topics/b/publish", json={"event_type": "e", "payload": {}, "publisher": "p"})

    r = api_client.get("/bus/consume", params={"consumer": "w", "topics": "a,b"})
    assert r.json()["count"] == 2


def test_error_envelope_on_empty_publisher(api_client):
    r = api_client.post("/bus/topics/t/publish", json={"event_type": "e", "payload": {}, "publisher": ""})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "comm_error"


def test_dispatch_round_robin_via_api(api_client):
    picks = []
    for _ in range(4):
        r = api_client.post("/bus/dispatch", json={
            "dispatch_key": "job", "candidates": ["a", "b"], "strategy": "round_robin",
        })
        assert r.status_code == 200
        picks.append(r.json()["selected"][0])
    assert picks == ["a", "b", "a", "b"]


def test_topics_and_consumers_listing_via_api(api_client):
    api_client.post("/bus/topics/t/publish", json={"event_type": "e", "payload": {}, "publisher": "p"})
    api_client.get("/bus/consume", params={"consumer": "w", "topics": "t"})

    r = api_client.get("/bus/topics")
    assert r.json()[0]["topic"] == "t"

    r = api_client.get("/bus/consumers")
    assert r.json()[0]["consumer"] == "w"


def test_reset_consumer_via_api(api_client):
    api_client.post("/bus/topics/t/publish", json={"event_type": "e", "payload": {}, "publisher": "p"})
    api_client.get("/bus/consume", params={"consumer": "w", "topics": "t"})
    assert api_client.get("/bus/consume", params={"consumer": "w", "topics": "t"}).json()["count"] == 0

    api_client.post("/bus/consumers/w/topics/t/reset", json={"to_id": 0})
    assert api_client.get("/bus/consume", params={"consumer": "w", "topics": "t"}).json()["count"] == 1
