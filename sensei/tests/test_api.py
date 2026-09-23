def test_health_and_info(api_client):
    r = api_client.get("/health")
    assert r.status_code == 200
    assert r.json()["organ"] == "sensei"

    r = api_client.get("/info")
    assert r.status_code == 200
    body = r.json()
    assert body["organ"] == "sensei"
    assert "mode" in body["capabilities"]


def test_default_status_is_watching(api_client):
    r = api_client.get("/sensei/status")
    assert r.status_code == 200
    assert r.json()["mode"] == "watching"


def test_set_mode_ready(api_client):
    r = api_client.post("/sensei/mode", json={"mode": "ready"})
    assert r.status_code == 200
    assert r.json()["mode"] == "ready"

    r = api_client.get("/sensei/status")
    assert r.json()["mode"] == "ready"


def test_set_mode_rejects_invalid(api_client):
    r = api_client.post("/sensei/mode", json={"mode": "asleep"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "sensei_error"


def test_nudge_suppressed_while_watching(api_client):
    r = api_client.post("/sensei/nudge", json={
        "kind": "shell", "message": "want an alias?", "source": "shell_watcher",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["delivered"] is False
    assert body["suppressed"] is True


def test_nudge_delivered_while_ready(api_client, monkeypatch):
    api_client.post("/sensei/mode", json={"mode": "ready"})

    delivered = []
    import main
    monkeypatch.setattr(main, "_deliver_toast", lambda m: delivered.append(m))

    r = api_client.post("/sensei/nudge", json={
        "kind": "shell", "message": "want an alias?", "source": "shell_watcher",
    })
    assert r.status_code == 200
    assert r.json()["delivered"] is True
    assert delivered == ["want an alias?"]


def test_nudge_rejects_empty_message(api_client):
    r = api_client.post("/sensei/nudge", json={
        "kind": "shell", "message": "   ", "source": "shell_watcher",
    })
    assert r.status_code == 400


def test_history_endpoint(api_client):
    api_client.post("/sensei/nudge", json={
        "kind": "shell", "message": "one", "source": "shell_watcher",
    })
    r = api_client.get("/sensei/history")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_respond_endpoint(api_client):
    r = api_client.post("/sensei/respond", json={"nudge_ts": 123.0, "accepted": True})
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is True
    assert body["nudge_ts"] == 123.0


def test_unknown_mode_returns_error_envelope(api_client):
    r = api_client.post("/sensei/mode", json={"mode": "sleeping"})
    assert r.status_code == 400
    assert "error" in r.json()
    assert "code" in r.json()["error"]


def test_detect_shell_no_pattern_returns_empty(api_client):
    r = api_client.post("/sensei/detect/shell", json={
        "commands": ["git status", "ls", "cd foo"],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["candidates_found"] == 0
    assert body["new_nudges"] == []


def test_detect_shell_finds_pattern_and_nudges_suppressed_while_watching(api_client):
    commands = ["git add .", "git commit -m wip"] * 3
    r = api_client.post("/sensei/detect/shell", json={"commands": commands})
    assert r.status_code == 200
    body = r.json()
    assert body["candidates_found"] == 1
    assert len(body["new_nudges"]) == 1
    assert body["new_nudges"][0]["delivered"] is False
    assert body["new_nudges"][0]["suppressed"] is True


def test_detect_shell_delivers_while_ready(api_client, monkeypatch):
    api_client.post("/sensei/mode", json={"mode": "ready"})
    delivered = []
    import main
    monkeypatch.setattr(main, "_deliver_toast", lambda m: delivered.append(m))

    commands = ["git add .", "git commit -m wip"] * 3
    r = api_client.post("/sensei/detect/shell", json={"commands": commands})
    body = r.json()
    assert body["new_nudges"][0]["delivered"] is True
    assert len(delivered) == 1
    assert "git add ." in delivered[0]


def test_detect_shell_does_not_renudge_the_same_chain_on_a_second_scan(api_client):
    commands = ["git add .", "git commit -m wip"] * 3

    r1 = api_client.post("/sensei/detect/shell", json={"commands": commands})
    assert r1.json()["candidates_found"] == 1
    assert len(r1.json()["new_nudges"]) == 1

    # same history scanned again (e.g. the watcher's next periodic tick,
    # chain still sitting in the recent-history window) — the pattern is
    # still found, but it must not nudge about it a second time.
    r2 = api_client.post("/sensei/detect/shell", json={"commands": commands})
    assert r2.json()["candidates_found"] == 1
    assert r2.json()["new_nudges"] == []


def test_detect_shell_appears_in_history_with_shell_watcher_source(api_client):
    api_client.post("/sensei/mode", json={"mode": "ready"})
    commands = ["make build", "make test", "make deploy"] * 3
    api_client.post("/sensei/detect/shell", json={"commands": commands})

    r = api_client.get("/sensei/history")
    entries = r.json()
    assert len(entries) == 1
    assert entries[0]["source"] == "shell_watcher"
    assert entries[0]["kind"] == "shell"


def test_detect_editor_no_storm_returns_empty(api_client):
    r = api_client.post("/sensei/detect/editor", json={
        "events": [
            {"type": "edit", "ts": 0, "file": "a.py"},
            {"type": "undo", "ts": 1, "file": "a.py"},
        ],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["storms_found"] == 0
    assert body["new_nudges"] == []


def test_detect_editor_finds_storm_and_nudges_suppressed_while_watching(api_client):
    events = [{"type": "undo", "ts": t, "file": "a.py"} for t in [0, 1, 2, 3]]
    r = api_client.post("/sensei/detect/editor", json={"events": events})
    assert r.status_code == 200
    body = r.json()
    assert body["storms_found"] == 1
    assert len(body["new_nudges"]) == 1
    assert body["new_nudges"][0]["delivered"] is False
    assert body["new_nudges"][0]["suppressed"] is True


def test_detect_editor_delivers_while_ready(api_client, monkeypatch):
    api_client.post("/sensei/mode", json={"mode": "ready"})
    delivered = []
    import main
    monkeypatch.setattr(main, "_deliver_toast", lambda m: delivered.append(m))

    events = [{"type": "undo", "ts": t, "file": "app.py"} for t in [0, 1, 2, 3]]
    r = api_client.post("/sensei/detect/editor", json={"events": events})
    body = r.json()
    assert body["new_nudges"][0]["delivered"] is True
    assert len(delivered) == 1
    assert "app.py" in delivered[0]


def test_detect_editor_does_not_renudge_the_same_storm_on_a_second_scan(api_client):
    events = [{"type": "undo", "ts": t, "file": "a.py"} for t in [0, 1, 2, 3]]

    r1 = api_client.post("/sensei/detect/editor", json={"events": events})
    assert r1.json()["storms_found"] == 1
    assert len(r1.json()["new_nudges"]) == 1

    r2 = api_client.post("/sensei/detect/editor", json={"events": events})
    assert r2.json()["storms_found"] == 1
    assert r2.json()["new_nudges"] == []


def test_detect_editor_new_storm_later_on_same_file_still_nudges(api_client):
    first_storm = [{"type": "undo", "ts": t, "file": "a.py"} for t in [0, 1, 2, 3]]
    second_storm = [{"type": "undo", "ts": t, "file": "a.py"} for t in [100, 101, 102, 103]]

    r1 = api_client.post("/sensei/detect/editor", json={"events": first_storm})
    assert len(r1.json()["new_nudges"]) == 1

    r2 = api_client.post("/sensei/detect/editor", json={"events": second_storm})
    assert len(r2.json()["new_nudges"]) == 1


def test_detect_editor_appears_in_history_with_editor_watcher_source(api_client):
    api_client.post("/sensei/mode", json={"mode": "ready"})
    events = [{"type": "undo", "ts": t, "file": "a.py"} for t in [0, 1, 2, 3]]
    api_client.post("/sensei/detect/editor", json={"events": events})

    r = api_client.get("/sensei/history")
    entries = r.json()
    assert len(entries) == 1
    assert entries[0]["source"] == "editor_watcher"
    assert entries[0]["kind"] == "editor"
