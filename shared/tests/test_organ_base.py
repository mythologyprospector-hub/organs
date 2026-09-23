import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

import organ_base


def make_app(monkeypatch):
    events = []
    monkeypatch.setattr(organ_base, "emit_telemetry", lambda *args, **kwargs: events.append((args, kwargs)))
    app = organ_base.create_organ_app("test_organ", "0.1.0", "test", ["test"])

    @app.get("/test/read")
    def read():
        return {"ok": True}

    @app.post("/test/write")
    def write():
        return {"changed": True}

    @app.get("/test/fail")
    def fail():
        raise organ_base.OrganError("test_error", "nope", 400)

    @app.get("/test/crash")
    def crash():
        raise ValueError("unanticipated bug")

    return app, events


def test_request_is_observed_and_correlation_id_is_returned(monkeypatch):
    app, events = make_app(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/test/read", headers={"X-Correlation-ID": "corr-123"})

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "corr-123"
    assert events[0][0][0] == "request"
    assert events[0][0][1] == "test_organ"
    assert events[0][1]["correlation_id"] == "corr-123"
    assert events[0][1]["payload"]["status_code"] == 200


def test_mutation_is_observed(monkeypatch):
    app, events = make_app(monkeypatch)
    monkeypatch.setattr(organ_base, "_ask_critic",
                         lambda organ, method, path, body: ("reversible", "test"))
    with TestClient(app) as client:
        response = client.post("/test/write")

    assert response.status_code == 200
    assert events[0][0][0] == "mutation"
    assert events[0][1]["status"] == "completed"


def test_failure_is_observed_after_standard_error_envelope(monkeypatch):
    app, events = make_app(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/test/fail")

    assert response.status_code == 400
    assert response.json() == {"error": {"code": "test_error", "message": "nope"}}
    assert events[0][0][0] == "failure"
    assert events[0][1]["status"] == "failed"
    assert events[0][1]["severity"] == "error"


def test_correlation_id_survives_an_unanticipated_crash(monkeypatch):
    """Regression test: an OrganError raised deliberately is caught by
    Starlette's ExceptionMiddleware, which sits INSIDE the telemetry
    middleware — so the correlation ID header gets set normally. A
    genuinely unanticipated exception (any other Exception subclass) is
    instead caught by ServerErrorMiddleware, which sits OUTSIDE it — by
    the time that handler runs, the telemetry middleware's own `finally`
    has already reset the correlation ID's ContextVar. Without reading
    it back from request.state instead, a real crash — precisely the
    response where correlating it against telemetry matters most —
    would come back with no X-Correlation-ID at all."""
    app, events = make_app(monkeypatch)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/test/crash", headers={"X-Correlation-ID": "crash-corr-789"})

    assert response.status_code == 500
    assert response.headers["X-Correlation-ID"] == "crash-corr-789"
    assert events[0][1]["correlation_id"] == "crash-corr-789"


def test_health_and_info_are_not_observed(monkeypatch):
    app, events = make_app(monkeypatch)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/info").status_code == 200

    assert events == []


def test_internal_telemetry_header_excludes_request_from_observation(monkeypatch):
    """Regression test: register()'s heartbeat POST to /registry/register
    didn't carry the same X-Telemetry-Internal exclusion header
    discover() already uses — meaning every organ's periodic heartbeat
    (12 organs, 10s default interval) generated a telemetry event on
    Registry, forever. This is the same category of pure plumbing
    /health and /info are already excluded for, just reachable only on
    one organ (Registry) rather than every organ, hence a header rather
    than a hardcoded path in this organ-agnostic file."""
    app, events = make_app(monkeypatch)
    monkeypatch.setattr(organ_base, "_ask_critic", lambda organ, method, path, body: ("safe", "test"))
    with TestClient(app) as client:
        response = client.post("/test/write", headers={"X-Telemetry-Internal": "1"})

    assert response.status_code == 200
    assert events == []


def test_telemetry_organ_does_not_observe_itself(monkeypatch):
    events = []
    monkeypatch.setattr(organ_base, "emit_telemetry", lambda *args, **kwargs: events.append((args, kwargs)))
    app = organ_base.create_organ_app("telemetry", "0.1.0", "test", [])

    @app.get("/telemetry/recent")
    def recent():
        return []

    with TestClient(app) as client:
        assert client.get("/telemetry/recent").status_code == 200

    assert events == []


def test_registry_timeout_is_translated_to_registry_error(monkeypatch):
    import organ_client

    monkeypatch.setattr(organ_client, "_post", lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("timed out")))
    try:
        organ_client.register("test", "http://127.0.0.1:1", "0.1", [])
    except organ_client.RegistryError as exc:
        assert "timed out" in str(exc)
    else:
        raise AssertionError("register() leaked TimeoutError")


def test_telemetry_path_uses_real_http_registry_and_telemetry_servers(monkeypatch):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    import organ_client

    # This test exercises the real discover()+telemetry HTTP round trip,
    # not the risk gate (that has its own dedicated tests above) — bypass
    # it here so a bare POST isn't blocked for lacking Critic classification.
    monkeypatch.setattr(organ_base, "_ask_critic", lambda organ, method, path, body: ("reversible", "test"))

    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/registry/organs/telemetry":
                body = json.dumps({"status": "alive", "base_url": f"http://127.0.0.1:{self.server.server_port}"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            if self.path == "/telemetry/events":
                length = int(self.headers.get("Content-Length", "0"))
                received.append(json.loads(self.rfile.read(length)))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(organ_client, "REGISTRY_URL", f"http://127.0.0.1:{server.server_port}")

    app = organ_base.create_organ_app("integration_probe", "0.1.0", "test", [])

    @app.post("/probe/change")
    def change():
        return {"changed": True}

    with TestClient(app) as client:
        response = client.post("/probe/change", headers={"X-Correlation-ID": "real-http-corr"})

    server.shutdown()
    thread.join(timeout=2)

    assert response.status_code == 200
    assert len(received) == 1
    assert received[0]["event_type"] == "mutation"
    assert received[0]["source"] == "integration_probe"
    assert received[0]["correlation_id"] == "real-http-corr"
    assert received[0]["payload"]["path"] == "/probe/change"


def test_correlation_id_is_available_to_outbound_calls(monkeypatch):
    """An existing organ endpoint can forward the current correlation ID
    without threading FastAPI's Request object through its helpers."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import urllib.request

    app, events = make_app(monkeypatch)
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append(self.headers.get("X-Correlation-ID"))
            body = b'{}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    @app.get("/test/proxy")
    def proxy():
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/echo",
            headers=organ_base.correlation_headers(),
        )
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return {"downstream": resp.status}

    try:
        with TestClient(app) as client:
            response = client.get("/test/proxy", headers={"X-Correlation-ID": "chain-123"})
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert response.status_code == 200
    assert received == ["chain-123"]


def test_discovery_forwards_current_correlation_id(monkeypatch):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import organ_client

    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append(self.headers.get("X-Correlation-ID"))
            if self.path == "/registry/organs/critic":
                body = json.dumps({
                    "status": "alive",
                    "base_url": "http://127.0.0.1:9999",
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(organ_client, "REGISTRY_URL", f"http://127.0.0.1:{server.server_port}")

    app, _ = make_app(monkeypatch)

    @app.get("/test/discover")
    def discover_probe():
        return {"url": organ_client.discover("critic")}

    try:
        with TestClient(app) as client:
            response = client.get("/test/discover", headers={"X-Correlation-ID": "discover-456"})
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert response.status_code == 200
    assert response.json()["url"] == "http://127.0.0.1:9999"
    assert received == ["discover-456"]


def test_gated_mutation_is_blocked_without_approval(monkeypatch):
    app, events = make_app(monkeypatch)
    monkeypatch.setattr(organ_base, "_ask_critic",
                         lambda organ, method, path, body: ("high_risk", "test reasoning"))

    with TestClient(app) as client:
        response = client.post("/test/write")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "requires_approval"
    assert "test reasoning" in response.json()["error"]["message"]


def test_gated_mutation_passes_with_executive_approved_header(monkeypatch):
    app, events = make_app(monkeypatch)
    monkeypatch.setattr(organ_base, "_ask_critic",
                         lambda organ, method, path, body: ("high_risk", "test reasoning"))

    with TestClient(app) as client:
        response = client.post("/test/write", headers={"X-Executive-Approved": "1"})

    assert response.status_code == 200
    assert response.json() == {"changed": True}


def test_gated_mutation_passes_with_explicit_bypass_header(monkeypatch, caplog):
    app, events = make_app(monkeypatch)
    monkeypatch.setattr(organ_base, "_ask_critic",
                         lambda organ, method, path, body: ("high_risk", "test reasoning"))

    with TestClient(app) as client:
        response = client.post("/test/write", headers={"X-Bypass-Safety": "testing locally"})

    assert response.status_code == 200
    assert "testing locally" in caplog.text


def test_bypass_is_never_the_default_only_an_explicit_opt_in(monkeypatch):
    """Doing nothing must get you the gate, not the bypass — the
    absence of a header is never itself treated as permission."""
    app, events = make_app(monkeypatch)
    monkeypatch.setattr(organ_base, "_ask_critic",
                         lambda organ, method, path, body: ("caution", "test reasoning"))

    with TestClient(app) as client:
        response = client.post("/test/write")

    assert response.status_code == 403


def test_safe_or_reversible_actions_pass_through_with_no_header_needed(monkeypatch):
    app, events = make_app(monkeypatch)
    monkeypatch.setattr(organ_base, "_ask_critic",
                         lambda organ, method, path, body: ("reversible", "routine write"))

    with TestClient(app) as client:
        response = client.post("/test/write")

    assert response.status_code == 200


def test_get_requests_never_trigger_the_gate(monkeypatch):
    """Even if Critic would (incorrectly) classify a GET as risky, the
    gate never even asks — GET is unconditionally exempt, matching
    Critic's own 'all GET is safe' rule and avoiding pointless latency
    on every single read."""
    app, events = make_app(monkeypatch)
    called = {"n": 0}

    def spy(*a, **k):
        called["n"] += 1
        return "high_risk", "should never be reached"

    monkeypatch.setattr(organ_base, "_ask_critic", spy)

    with TestClient(app) as client:
        response = client.get("/test/read")

    assert response.status_code == 200
    assert called["n"] == 0


def test_exempt_paths_skip_critic_entirely(monkeypatch):
    """A path in risk_gate_exempt_paths must never even call Critic —
    not 'call it and get safe back', genuinely skip the call. This is
    what protects infrastructure like Registry's own /registry/register
    from a circular dependency on Critic being reachable at boot."""
    events = []
    monkeypatch.setattr(organ_base, "emit_telemetry", lambda *a, **k: events.append((a, k)))
    app = organ_base.create_organ_app(
        "test_organ", "0.1.0", "test", ["test"],
        risk_gate_exempt_paths={"/test/infra"},
    )

    @app.post("/test/infra")
    def infra():
        return {"registered": True}

    called = {"n": 0}

    def spy(*a, **k):
        called["n"] += 1
        return "high_risk", "should never be reached"

    monkeypatch.setattr(organ_base, "_ask_critic", spy)

    with TestClient(app) as client:
        response = client.post("/test/infra")

    assert response.status_code == 200
    assert called["n"] == 0


def test_critic_organ_is_automatically_exempt_from_gating_itself(monkeypatch):
    """The arbiter cannot ask itself for permission to arbitrate —
    same category of self-recursion guard as telemetry already has for
    its own organ name."""
    events = []
    monkeypatch.setattr(organ_base, "emit_telemetry", lambda *a, **k: events.append((a, k)))
    app = organ_base.create_organ_app("critic", "0.1.0", "test", ["evaluate"])

    @app.post("/critic/evaluate")
    def evaluate():
        return {"risk_tier": "safe"}

    called = {"n": 0}

    def spy(*a, **k):
        called["n"] += 1
        return "high_risk", "should never be reached"

    monkeypatch.setattr(organ_base, "_ask_critic", spy)

    with TestClient(app) as client:
        response = client.post("/critic/evaluate")

    assert response.status_code == 200
    assert called["n"] == 0


def test_gate_fails_closed_when_critic_is_unreachable(monkeypatch):
    """_ask_critic itself — not the gate wiring — must treat an
    unreachable Critic as high_risk, never as safe. 'I can't tell if
    this is dangerous' is not the same claim as 'this is fine'."""
    import organ_client
    monkeypatch.setattr(organ_client, "REGISTRY_URL", "http://127.0.0.1:1")  # guaranteed-dead
    tier, reasoning = organ_base._ask_critic("test_organ", "POST", "/test/write", None)
    assert tier == "high_risk"
    assert "unreachable" in reasoning
