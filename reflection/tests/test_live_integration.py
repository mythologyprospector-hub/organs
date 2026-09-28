import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi.testclient import TestClient


def test_reflection_live_memory_ollama_chain(monkeypatch, tmp_path):
    """Prove Reflection reads Memory, calls Ollama, and writes back to Memory."""
    monkeypatch.setenv("REFLECTION_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("REFLECTION_HISTORY_PATH", str(tmp_path / "history.jsonl"))
    monkeypatch.setenv("REFLECTION_BASE_URL", "http://127.0.0.1:8004")
    monkeypatch.setenv("ORGAN_TELEMETRY_ENABLED", "0")

    received = {"memory_list": [], "ollama": [], "memory_add": []}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/registry/organs/memory"):
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

            if self.path.startswith("/memory/list"):
                received["memory_list"].append(self.path)
                body = json.dumps([{"text": "live integration activity"}]).encode()
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

            if self.path == "/registry/register":
                body = b'{"status":"registered"}'
            elif self.path == "/api/generate":
                received["ollama"].append(request)
                body = json.dumps({"response": "A live reflection was generated."}).encode()
            elif self.path == "/memory/add":
                received["memory_add"].append(request)
                body = json.dumps({"id": 42, "text": request["text"]}).encode()
            else:
                self.send_response(404)
                self.end_headers()
                return

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

    try:
        monkeypatch.setenv(
            "ORGAN_REGISTRY_URL",
            f"http://127.0.0.1:{server.server_port}",
        )
        monkeypatch.setenv(
            "OLLAMA_HOST",
            f"http://127.0.0.1:{server.server_port}",
        )

        import importlib
        import organ_client
        importlib.reload(organ_client)
        import reflection_core
        importlib.reload(reflection_core)
        import main
        importlib.reload(main)

        with TestClient(main.app) as client:
            response = client.post("/reflection/tick")

        assert response.status_code == 200
        body = response.json()
        assert body["ran"] is True
        assert body["success"] is True
        assert body["thought"] == "A live reflection was generated."
        assert body["write_result"] == {
            "id": 42,
            "text": "A live reflection was generated.",
        }

        assert received["memory_list"] == ["/memory/list?n=8"]
        assert len(received["ollama"]) == 1
        assert received["ollama"][0]["model"] == "phi4-mini:latest"
        assert "live integration activity" in received["ollama"][0]["prompt"]
        assert received["memory_add"] == [{
            "text": "A live reflection was generated.",
            "tags": ["reflection"],
            "provenance": "self",
            "witness": "inferred",
            "confidence": 0.3,
            "owner": "reflection",
        }]
    finally:
        server.shutdown()
        thread.join(timeout=2)
