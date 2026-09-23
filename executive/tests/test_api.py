def test_health_and_info(api_client):
    r = api_client.get("/health")
    assert r.status_code == 200
    r = api_client.get("/info")
    assert "submit_plan" in r.json()["capabilities"]


def test_create_goal_via_api(api_client):
    r = api_client.post("/executive/goals", json={"description": "test goal"})
    assert r.status_code == 200
    assert r.json()["status"] == "draft"


def test_submit_plan_via_api_with_no_registry_fails_closed(api_client):
    """No registry running in the test env — Critic is genuinely
    unreachable. The step must still come back requiring approval,
    proving the real fail-closed path in main.py's _evaluate_risk."""
    goal = api_client.post("/executive/goals", json={"description": "x"}).json()
    r = api_client.post(f"/executive/goals/{goal['id']}/plan", json={
        "steps": [{"organ": "memory", "method": "GET", "path": "/memory/stats"}],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "awaiting_approval"
    assert body["steps"][0]["requires_human_approval"] is True
    assert "unreachable" in body["steps"][0]["risk_reasoning"] or "failing closed" in body["steps"][0]["risk_reasoning"]


def test_approve_and_execute_with_no_target_organ_fails_cleanly(api_client):
    """Approving works even with no registry (it's a local decision);
    executing then fails cleanly since the target organ can't be found
    — not a crash, a reported step failure."""
    goal = api_client.post("/executive/goals", json={"description": "x"}).json()
    plan = api_client.post(f"/executive/goals/{goal['id']}/plan", json={
        "steps": [{"organ": "memory", "method": "GET", "path": "/memory/stats"}],
    }).json()
    step_id = plan["steps"][0]["id"]

    api_client.post(f"/executive/goals/{goal['id']}/steps/{step_id}/approve", json={})
    r = api_client.post(f"/executive/goals/{goal['id']}/execute_next")
    assert r.status_code == 200
    assert r.json()["step_status"] == "failed"


def test_reject_via_api(api_client):
    goal = api_client.post("/executive/goals", json={"description": "x"}).json()
    plan = api_client.post(f"/executive/goals/{goal['id']}/plan", json={
        "steps": [{"organ": "memory", "method": "GET", "path": "/memory/stats"}],
    }).json()
    step_id = plan["steps"][0]["id"]

    r = api_client.post(f"/executive/goals/{goal['id']}/steps/{step_id}/reject", json={"reason": "no"})
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"


def test_list_and_get_goals_via_api(api_client):
    api_client.post("/executive/goals", json={"description": "a"})
    api_client.post("/executive/goals", json={"description": "b"})
    r = api_client.get("/executive/goals")
    assert len(r.json()) == 2


def test_unknown_goal_returns_error_envelope(api_client):
    r = api_client.get("/executive/goals/nonexistent")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "executive_error"

def test_execute_call_uses_generous_timeout_not_15_seconds(tmp_path, monkeypatch):
    """Regression test: _execute_call used to hard-code a 15s client
    timeout for every step, regardless of target. Forge's own single
    generation call is independently configured for up to 180s
    (FORGE_GENERATE_TIMEOUT), and a /forge/build call with max_retries
    set can chain several of those plus several Sandbox runs within ONE
    call — routinely exceeding 15s with no code bug involved. A short
    timeout here didn't stop that work (Forge keeps running with no
    way to know its caller gave up); it just made Executive report a
    false 'step failed' while the build's real result later landed in
    Forge's workspace orphaned from the goal that requested it."""
    import importlib
    monkeypatch.setenv("EXECUTIVE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EXECUTIVE_BASE_URL", "http://localhost:8008")
    monkeypatch.setenv("ORGAN_REGISTRY_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ORGAN_TELEMETRY_ENABLED", "0")

    import executive_core
    importlib.reload(executive_core)
    import main
    importlib.reload(main)

    monkeypatch.setattr(main, "discover", lambda organ: "http://forge-fake")

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return b"{}"

    def fake_urlopen(req, timeout=None):
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(main.urllib.request, "urlopen", fake_urlopen)

    main._execute_call("forge", "POST", "/forge/build", {"spec": "x", "max_retries": 3})

    assert captured["timeout"] == main.STEP_EXECUTION_TIMEOUT
    assert captured["timeout"] >= 900  # generous enough for a real multi-attempt retry chain
