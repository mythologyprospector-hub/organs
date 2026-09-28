import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi.testclient import TestClient


def test_executive_live_chain_registry_critic_target(monkeypatch, tmp_path):
    """Prove the existing Executive chain against real local HTTP servers."""
    monkeypatch.setenv("EXECUTIVE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EXECUTIVE_BASE_URL", "http://127.0.0.1:8008")
    monkeypatch.setenv("ORGAN_TELEMETRY_ENABLED", "0")

    received = {"critic": [], "target": []}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/registry/organs/"):
                name = self.path.rsplit("/", 1)[-1]
                urls = {
                    "critic": f"http://127.0.0.1:{self.server.server_port}",
                    "memory": f"http://127.0.0.1:{self.server.server_port}",
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

            if self.path == "/memory/stats":
                received["target"].append(self.headers.get("X-Executive-Approved"))
                body = json.dumps({"live": True}).encode()
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
                    "risk_tier": "safe",
                    "reasoning": "live integration classification",
                    "requires_human_approval": False,
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
        import executive_core
        importlib.reload(executive_core)
        import main
        importlib.reload(main)

        with TestClient(main.app) as client:
            goal = client.post(
                "/executive/goals", json={"description": "live chain"}
            ).json()
            plan = client.post(
                f"/executive/goals/{goal['id']}/plan",
                json={"steps": [{
                    "organ": "memory",
                    "method": "GET",
                    "path": "/memory/stats",
                }]},
            )
            assert plan.status_code == 200
            assert plan.json()["status"] == "ready"

            result = client.post(
                f"/executive/goals/{goal['id']}/execute_next"
            )
            assert result.status_code == 200
            assert result.json()["step_status"] == "succeeded"
            assert result.json()["result"] == {"live": True}

        assert len(received["critic"]) == 1
        assert received["critic"][0] == {
            "organ": "memory",
            "method": "GET",
            "path": "/memory/stats",
            "body": None,
        }
        assert received["target"] == ["1"]
    finally:
        server.shutdown()
        thread.join(timeout=2)
