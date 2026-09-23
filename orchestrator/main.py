"""
main.py — the Orchestrator organ.

Run it:
    pip install fastapi uvicorn --break-system-packages
    uvicorn main:app --host 127.0.0.1 --port 8003

Edit services.json (created on first run with sensible defaults for
Ollama/Open WebUI, and a placeholder for the OI sandbox container name
you'll need to fill in) to change what it manages.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))

from organ_base import create_organ_app, HealthCheck, OrganError  # noqa: E402
from organ_client import attach_to_registry  # noqa: E402
import orchestrator_core as oc  # noqa: E402

# Create services.json immediately on startup, not lazily on first
# request — so `cat services.json` right after starting the service
# always shows real content, never an accidental empty file waiting for
# someone to hit an endpoint first.
oc.ensure_config()

ORGAN_NAME = "orchestrator"
ORGAN_VERSION = "0.1.0"
SELF_BASE_URL = os.environ.get("ORCH_BASE_URL", "http://localhost:8003")

CAPABILITIES = ["list_services", "get_service", "start", "stop", "restart", "doctor"]


def _config_check():
    try:
        oc.ensure_config()
        oc.load_services()
        return True, f"config OK at {oc.CONFIG_PATH}"
    except oc.OrchestratorError as e:
        return False, str(e)


app = create_organ_app(
    name=ORGAN_NAME,
    version=ORGAN_VERSION,
    description="Orchestrator organ: manages a fixed, config-defined set of "
                "OS-level services (Ollama, Open WebUI, the OI sandbox) that "
                "organs depend on. Never accepts arbitrary commands from the API.",
    capabilities=CAPABILITIES,
    health_checks=[HealthCheck("config", _config_check)],
)

attach_to_registry(app, name=ORGAN_NAME, base_url=SELF_BASE_URL, version=ORGAN_VERSION, capabilities=CAPABILITIES)


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except oc.OrchestratorError as e:
        raise OrganError(code="orchestrator_error", message=str(e), status_code=400)


@app.get("/orchestrator/services")
def list_services():
    return _wrap(oc.op_list)


@app.get("/orchestrator/services/{name}")
def get_service(name: str):
    return _wrap(oc.op_get, name)


@app.post("/orchestrator/services/{name}/start")
def start_service(name: str):
    return _wrap(oc.op_start, name)


@app.post("/orchestrator/services/{name}/stop")
def stop_service(name: str):
    return _wrap(oc.op_stop, name)


@app.post("/orchestrator/services/{name}/restart")
def restart_service(name: str):
    return _wrap(oc.op_restart, name)


@app.get("/orchestrator/doctor")
def doctor():
    return _wrap(oc.op_doctor)
