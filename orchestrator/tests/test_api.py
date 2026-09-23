def test_health_and_info(api_client):
    r = api_client.get("/health")
    assert r.status_code == 200
    assert r.json()["organ"] == "orchestrator"

    r = api_client.get("/info")
    assert "start" in r.json()["capabilities"]


def test_advertised_capabilities_include_doctor(api_client):
    """The organ has a real /orchestrator/doctor endpoint (used for its
    own health check and available to any caller) — the capabilities
    list published to the registry must say so, the same way Sandbox's
    identical doctor endpoint is advertised in its own CAPABILITIES."""
    r = api_client.get("/info")
    assert "doctor" in r.json()["capabilities"]

    r = api_client.get("/orchestrator/doctor")
    assert r.status_code == 200


def test_list_services_via_api(api_client):
    api_client.fake_runner.default = (0, "active", "")
    api_client.fake_runner.responses[("docker", "inspect", "-f", "{{.State.Running}}", "open-webui")] = (0, "true", "")
    api_client.fake_runner.responses[("docker", "inspect", "-f", "{{.State.Running}}", "REPLACE_ME_oi_container_name")] = (0, "false", "")

    r = api_client.get("/orchestrator/services")
    assert r.status_code == 200
    names = {s["name"] for s in r.json()}
    assert names == {"ollama", "open-webui", "oi-sandbox"}


def test_unknown_service_returns_error_envelope(api_client):
    r = api_client.get("/orchestrator/services/nonexistent")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "orchestrator_error"


def test_start_already_running_via_api(api_client):
    api_client.fake_runner.responses[("systemctl", "is-active", "ollama.service")] = (0, "active", "")
    r = api_client.post("/orchestrator/services/ollama/start")
    assert r.status_code == 200
    assert r.json()["detail"] == "already running"


def test_doctor_via_api(api_client):
    r = api_client.get("/orchestrator/doctor")
    assert r.status_code == 200
    assert r.json()["service_count"] == 3


def test_direct_restart_without_executive_approval_is_blocked(tmp_path, monkeypatch):
    """THE regression test for the vulnerability this whole risk-gate
    system exists to close: a security audit found that
    /orchestrator/services/{name}/restart called the OS directly with
    zero Critic check — Executive correctly asked Critic first, but
    nothing stopped a direct HTTP call from skipping Executive
    entirely. This constructs its own TestClient WITHOUT the api_client
    fixture's gate bypass, mocks _ask_critic to return exactly what
    Critic's own real rule table says for this endpoint ("touches a
    real OS-level service" -> high_risk), and proves a bare direct call
    is now rejected — while a call carrying X-Executive-Approved (what
    Executive's real _execute_call actually sets after a step is
    genuinely approved) still succeeds."""
    import importlib
    from fastapi.testclient import TestClient
    import organ_base

    monkeypatch.setenv("ORCH_CONFIG_PATH", str(tmp_path / "services.json"))
    monkeypatch.setenv("ORCH_BASE_URL", "http://localhost:8003")
    monkeypatch.setenv("ORGAN_REGISTRY_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ORGAN_TELEMETRY_ENABLED", "0")

    import orchestrator_core
    importlib.reload(orchestrator_core)
    import main
    importlib.reload(main)

    calls = []
    scripted = {("systemctl", "is-active", "ollama.service"): (3, "inactive", ""),
                ("sudo", "-n", "systemctl", "start", "ollama.service"): (0, "", "")}

    def fake_run(cmd, timeout=10):
        calls.append(tuple(cmd))
        return scripted.get(tuple(cmd), (0, "", ""))

    monkeypatch.setattr(main.oc, "_run", fake_run)

    monkeypatch.setattr(
        organ_base, "_ask_critic",
        lambda organ, method, path, body: ("high_risk", "touches a real OS-level service"),
    )

    with TestClient(main.app) as client:
        blocked = client.post("/orchestrator/services/ollama/start")
        approved = client.post("/orchestrator/services/ollama/start",
                                headers={"X-Executive-Approved": "1"})

    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "requires_approval"

    assert approved.status_code == 200
