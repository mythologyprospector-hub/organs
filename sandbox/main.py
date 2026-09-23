"""
main.py — the Sandbox organ.

Run it:
    pip install fastapi uvicorn --break-system-packages
    uvicorn main:app --host 127.0.0.1 --port 8006

Requires Docker on the host. Check readiness with GET /sandbox/doctor.
"""
import os
import sys
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))

from organ_base import create_organ_app, HealthCheck, OrganError  # noqa: E402
from organ_client import attach_to_registry  # noqa: E402
import sandbox_core as sc  # noqa: E402

ORGAN_NAME = "sandbox"
ORGAN_VERSION = "0.1.0"
SELF_BASE_URL = os.environ.get("SANDBOX_BASE_URL", "http://localhost:8006")

CAPABILITIES = ["run_job", "languages", "doctor"]


def _docker_check():
    result = sc.op_doctor()
    if result["docker_available"]:
        return True, result["docker_version"]
    return False, "docker not available — Sandbox cannot run jobs"


app = create_organ_app(
    name=ORGAN_NAME,
    version=ORGAN_VERSION,
    description="Sandbox organ: runs code in ephemeral, isolated Docker "
                 "containers from a fixed set of pre-approved base images. "
                 "No network by default, hard resource limits, workspace "
                 "always destroyed after every job. Safety comes from "
                 "containment, not review — nothing here persists or "
                 "becomes trusted automatically.",
    capabilities=CAPABILITIES,
    health_checks=[HealthCheck("docker", _docker_check)],
)

attach_to_registry(app, name=ORGAN_NAME, base_url=SELF_BASE_URL, version=ORGAN_VERSION, capabilities=CAPABILITIES)


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except sc.SandboxError as e:
        raise OrganError(code="sandbox_error", message=str(e), status_code=400)


class RunJobRequest(BaseModel):
    language: str
    files: dict[str, str]
    command: str
    timeout_seconds: Optional[int] = None
    network: bool = False
    memory: Optional[str] = None
    cpus: Optional[str] = None


@app.post("/sandbox/jobs")
def run_job(req: RunJobRequest):
    return _wrap(sc.op_run_job, req.language, req.files, req.command,
                 req.timeout_seconds, req.network, req.memory, req.cpus)


@app.get("/sandbox/languages")
def languages():
    return _wrap(sc.op_list_languages)


@app.get("/sandbox/doctor")
def doctor():
    return _wrap(sc.op_doctor)
