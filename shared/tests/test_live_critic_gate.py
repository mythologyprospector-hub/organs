import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi.testclient import TestClient

import organ_base
import organ_client


def test_real_critic_http_path_enforces_risk_gate(monkeypatch):
    """Exercise the production Critic HTTP path, not a mocked _ask_critic."""
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/registry/organs/critic":
                body = json.dumps({
                    "status": "alive",
                    "base_url": f"http://127.0.0.1:{self.server.server_port}",
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            if self.path == "/critic/evaluate":
                length = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(length))
                received.append(request)
                body = json.dumps({
                    "risk_tier": "high_risk",
                    "reasoning": "live test classification",
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

    app = organ_base.create_organ_app("integration_probe", "0.1.0", "test", [])

    @app.post("/probe/change")
    def change():
        return {"changed": True}

    try:
        with TestClient(app) as client:
            response = client.post("/probe/change")
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "requires_approval"
    assert len(received) == 1
    assert received[0] == {
        "organ": "integration_probe",
        "method": "POST",
        "path": "/probe/change",
        "body": None,
    }
