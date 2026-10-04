"""The existing operational front door plus bounded Renaissance semantic handoff."""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from pydantic import BaseModel
from fastapi.responses import HTMLResponse

from web_ui import render

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))

from organ_base import create_organ_app, OrganError, correlation_headers  # noqa: E402
from organ_client import attach_to_registry, discover, RegistryError  # noqa: E402
import io_interface_core as ioc  # noqa: E402

ORGAN_NAME = "io_interface"
ORGAN_VERSION = "0.1.0"
SELF_BASE_URL = os.environ.get("IO_BASE_URL", "http://localhost:8009")
CAPABILITIES = ["handle", "interpret", "catalog"]

app = create_organ_app(
    name=ORGAN_NAME,
    version=ORGAN_VERSION,
    description="Existing operational front door with a bounded Renaissance semantic handoff for non-operational expressions.",
    capabilities=CAPABILITIES,
)
attach_to_registry(app, name=ORGAN_NAME, base_url=SELF_BASE_URL, version=ORGAN_VERSION, capabilities=CAPABILITIES)


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ioc.IOError_ as e:
        raise OrganError(code="io_interface_error", message=str(e), status_code=400)


def _evaluate_risk(organ, method, path, body):
    try:
        critic_url = discover("critic")
    except RegistryError as e:
        return {"risk_tier": "high_risk", "requires_human_approval": True, "reasoning": f"Critic unreachable ({e}) — failing closed"}
    payload = json.dumps({"organ": organ, "method": method, "path": path, "body": body}).encode("utf-8")
    req = urllib.request.Request(
        f"{critic_url}/critic/evaluate",
        data=payload,
        headers=correlation_headers({"Content-Type": "application/json"}),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        return {"risk_tier": "high_risk", "requires_human_approval": True, "reasoning": f"Critic call failed ({e}) — failing closed"}


def _execute_call(organ, method, path, body):
    target_url = discover(organ)
    payload = json.dumps(body or {}).encode("utf-8") if method.upper() in ("POST", "PUT", "DELETE") else None
    req = urllib.request.Request(
        f"{target_url}{path}",
        data=payload,
        headers=correlation_headers({"Content-Type": "application/json"}),
        method=method.upper(),
    )
    with urllib.request.urlopen(req, timeout=15.0) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else None


def _create_gated_goal(original_text, organ, method, path, body):
    try:
        executive_url = discover("executive")
    except RegistryError as e:
        return {"error": f"executive unreachable ({e}) — could not create a goal for approval"}

    goal_payload = json.dumps({"description": original_text, "created_by": "io_interface"}).encode("utf-8")
    req = urllib.request.Request(
        f"{executive_url}/executive/goals",
        data=goal_payload,
        headers=correlation_headers({"Content-Type": "application/json"}),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            goal = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        return {"error": f"could not create goal: {e}"}

    plan_payload = json.dumps({
        "steps": [{"organ": organ, "method": method, "path": path, "body": body, "description": original_text}]
    }).encode("utf-8")
    req2 = urllib.request.Request(
        f"{executive_url}/executive/goals/{goal['id']}/plan",
        data=plan_payload,
        headers=correlation_headers({"Content-Type": "application/json"}),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req2, timeout=10.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        return {"error": f"goal created but plan submission failed: {e}", "goal_id": goal.get("id")}


def _renaissance_handoff(text):
    try:
        renaissance_url = discover("renaissance")
    except RegistryError:
        return None

    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        f"{renaissance_url}/renaissance/doorway",
        data=payload,
        headers=correlation_headers({"Content-Type": "application/json"}),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, UnicodeError):
        # An unavailable or malformed semantic service must not break the
        # existing operational front door or manufacture a disposition.
        return None


class HandleRequest(BaseModel):
    text: str


@app.get("/", response_class=HTMLResponse)
def web_ui():
    return render()


@app.post("/io/handle")
def handle(req: HandleRequest):
    return _wrap(ioc.op_handle, req.text, _evaluate_risk, _execute_call, _create_gated_goal, _renaissance_handoff)


@app.post("/io/interpret")
def interpret(req: HandleRequest):
    return _wrap(ioc.op_interpret, req.text, _renaissance_handoff)


@app.get("/io/catalog")
def catalog():
    return [{"intent": e["name"], "organ": e["organ"], "method": e["method"], "example": e["example"]} for e in ioc.CATALOG]
