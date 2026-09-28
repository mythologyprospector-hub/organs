import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi.testclient import TestClient


def test_io_interface_live_gate_chain_registry_critic_executive(monkeypatch, tmp_path):
    """Prove the existing I/O Interface approval path against real HTTP."""
    monkeypatch.setenv("IO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("IO_BASE_URL", "http://127.0.0.1:8009")
    monkeypatch.setenv("ORGAN_TELEMETRY_ENABLED", "0")

    received = {"critic": [], "executive": []}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/registry/organs/"):
                name = self.path.rsplit("/", 1)[-1]
                urls = {
                    "critic": f"http://127.0.0.1:{self.server.server_port}",
                    "executive": f"http://127.0.0.1:{self.server.server_port}",
                }
                if name not in urls:
                    self.send_response(404)
                    self.end_headers()
                    return
                body = json.dumps({"status": "alive", "base_url": urls[name]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length)) if length else None

            if self.path == "/critic/evaluate":
                received["critic"].append(request)
                body = json.dumps({
                    "risk_tier": "high_risk",
                    "reasoning": "live integration classification",
                    "requires_human_approval": True,
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path == "/registry/register":
                body = b'{"status":"registered"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path == "/executive/goals":
                received["executive"].append(("create", request))
                body = json.dumps({
                    "id": "live-goal",
                    "description": request["description"],
                    "created_by": "io_interface",
                    "status": "draft",
                    "steps": [],
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path == "/executive/goals/live-goal/plan":
                received["executive"].append(("plan", request))
                body = json.dumps({
                    "id": "live-goal",
                    "status": "awaiting_approval",
                    "steps": [{
                        "organ": "orchestrator",
                        "method": "POST",
                        "path": "/orchestrator/services/ollama/restart",
                    }],
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

    try:
        monkeypatch.setenv(
            "ORGAN_REGISTRY_URL",
            f"http://127.0.0.1:{server.server_port}",
        )
        import importlib
        import organ_client
        importlib.reload(organ_client)
        import io_interface_core
        importlib.reload(io_interface_core)
        import main
        importlib.reload(main)

        with TestClient(main.app) as client:
            response = client.post(
                "/io/handle",
                json={"text": "restart ollama"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["action_taken"] is False
        assert body["needs_approval"] is True
        assert body["goal"]["id"] == "live-goal"
        assert body["goal"]["status"] == "awaiting_approval"

        assert received["critic"] == [{
            "organ": "orchestrator",
            "method": "POST",
            "path": "/orchestrator/services/ollama/restart",
            "body": None,
        }]
        assert received["executive"] == [
            ("create", {
                "description": "restart ollama",
                "created_by": "io_interface",
            }),
            ("plan", {
                "steps": [{
                    "organ": "orchestrator",
                    "method": "POST",
                    "path": "/orchestrator/services/ollama/restart",
                    "body": None,
                    "description": "restart ollama",
                }],
            }),
        ]
    finally:
        server.shutdown()
        thread.join(timeout=2)
