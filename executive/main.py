"""
main.py — the Executive organ.

Run it:
    pip install fastapi uvicorn --break-system-packages
    uvicorn main:app --host 127.0.0.1 --port 8008
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))

from organ_base import create_organ_app, OrganError, correlation_headers  # noqa: E402
from organ_client import attach_to_registry, discover, RegistryError  # noqa: E402
import executive_core as ec  # noqa: E402

ORGAN_NAME = "executive"
ORGAN_VERSION = "0.1.0"
SELF_BASE_URL = os.environ.get("EXECUTIVE_BASE_URL", "http://localhost:8008")

CAPABILITIES = ["create_goal", "submit_plan", "approve_step", "reject_step", "execute_next_step", "get_goal", "list_goals"]

# Sized off Forge's own worst case: FORGE_GENERATE_TIMEOUT defaults to
# 180s per Ollama call, and a /forge/build with max_retries set can
# chain up to (1 + MAX_RETRIES_CAP) implementation regenerations plus
# one test generation, each up to 180s, plus a Sandbox run per attempt
# (Forge's own client-side Sandbox-call timeout is 120s) — all within
# ONE call to /forge/build. The true worst case across those configured
# ceilings is roughly half an hour; 1800s covers a realistic retry
# chain without reaching all the way to that theoretical maximum. See
# _execute_call's docstring for why this is one blunt, generic value
# rather than special-cased per organ.
STEP_EXECUTION_TIMEOUT = 1800.0

app = create_organ_app(
    name=ORGAN_NAME,
    version=ORGAN_VERSION,
    description="Executive organ: goal/plan/step tracking with MANDATORY "
                 "Critic-gated execution. Plans are explicit, submitted "
                 "step lists — no autonomous LLM planning yet. Every step "
                 "is risk-classified before it can run; caution/high_risk "
                 "steps always halt for a human decision, no exceptions.",
    capabilities=CAPABILITIES,
)

attach_to_registry(app, name=ORGAN_NAME, base_url=SELF_BASE_URL, version=ORGAN_VERSION, capabilities=CAPABILITIES)


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ec.ExecutiveError as e:
        raise OrganError(code="executive_error", message=str(e), status_code=400)


def _evaluate_risk(organ: str, method: str, path: str, body: dict):
    """Real implementation: ask the real Critic organ. If Critic itself
    is unreachable, fail closed — never let a step skip review just
    because the reviewer happened to be down."""
    try:
        critic_url = discover("critic")
    except RegistryError as e:
        return {"risk_tier": "high_risk", "requires_human_approval": True,
                "reasoning": f"Critic unreachable ({e}) — failing closed"}

    payload = json.dumps({"organ": organ, "method": method, "path": path, "body": body}).encode("utf-8")
    req = urllib.request.Request(
        f"{critic_url}/critic/evaluate", data=payload,
        headers=correlation_headers({"Content-Type": "application/json"}), method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        return {"risk_tier": "high_risk", "requires_human_approval": True,
                "reasoning": f"Critic call failed ({e}) — failing closed"}


def _execute_call(organ: str, method: str, path: str, body: dict):
    """Real implementation: discover the target organ, make the actual
    call. Raises on failure — op_execute_next_step in the core handles
    turning that into a clean 'step failed' result rather than crashing.

    STEP_EXECUTION_TIMEOUT is deliberately generous, not a quick
    fail-fast value like Critic's own 5s check above. Forge's own
    single generation call is independently configured for up to 180s
    (FORGE_GENERATE_TIMEOUT), and a /forge/build call with max_retries
    set can chain several of those plus several Sandbox runs in
    sequence, all within ONE HTTP call to /forge/build. A short client
    timeout here doesn't stop that work — Forge keeps running
    regardless, with no way to know its caller gave up — it just makes
    Executive give up on it, mark the step failed, and let the build's
    eventual real result land in Forge's workspace completely orphaned
    from the goal that requested it, with nothing in Executive
    reflecting what actually happened.

    This is deliberately one generic timeout, not special-cased per
    target organ or path — Executive treats every step the same way
    Critic evaluates every request the same way, by generic rule, not
    by knowing what any particular organ's endpoint specifically does.
    The honest tradeoff: a step against a genuinely hung OTHER organ
    (not Forge) now also takes this long to time out, instead of 15s.
    That's judged the better failure mode of the two — a slow, correct
    failure eventually reported, vs. a fast failure that's actually
    wrong, silently orphaning real completed work."""
    target_url = discover(organ)  # raises RegistryError if unreachable — that's fine, caller catches it
    payload = json.dumps(body or {}).encode("utf-8") if method.upper() in ("POST", "PUT", "DELETE") else None
    # X-Executive-Approved tells the target organ's own risk gate this
    # step already went through the real flow — either auto-approved as
    # safe/reversible by Critic during op_submit_plan, or explicitly
    # approved by a human via op_approve_step. _execute_call is only
    # ever reached for a step in one of those two states (op_execute_
    # next_step returns "blocked" without calling this at all for a
    # step still pending_approval) — so it's correct to set this
    # unconditionally here, not a blanket bypass for anything Executive
    # might call.
    req = urllib.request.Request(
        f"{target_url}{path}", data=payload,
        headers=correlation_headers({"Content-Type": "application/json", "X-Executive-Approved": "1"}),
        method=method.upper(),
    )
    with urllib.request.urlopen(req, timeout=STEP_EXECUTION_TIMEOUT) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else None


class CreateGoalRequest(BaseModel):
    description: str
    created_by: str = "user"


class PlanStep(BaseModel):
    organ: str
    method: str
    path: str
    body: Optional[dict] = None
    description: str = ""


class SubmitPlanRequest(BaseModel):
    steps: list[PlanStep]


class ApproveRequest(BaseModel):
    approved_by: str = "user"


class RejectRequest(BaseModel):
    reason: str = ""


@app.post("/executive/goals")
def create_goal(req: CreateGoalRequest):
    return _wrap(ec.op_create_goal, req.description, req.created_by)


@app.post("/executive/goals/{goal_id}/plan")
def submit_plan(goal_id: str, req: SubmitPlanRequest):
    steps = [s.model_dump() for s in req.steps]
    return _wrap(ec.op_submit_plan, goal_id, steps, _evaluate_risk)


@app.post("/executive/goals/{goal_id}/steps/{step_id}/approve")
def approve_step(goal_id: str, step_id: str, req: ApproveRequest):
    return _wrap(ec.op_approve_step, goal_id, step_id, req.approved_by)


@app.post("/executive/goals/{goal_id}/steps/{step_id}/reject")
def reject_step(goal_id: str, step_id: str, req: RejectRequest):
    return _wrap(ec.op_reject_step, goal_id, step_id, req.reason)


@app.post("/executive/goals/{goal_id}/execute_next")
def execute_next_step(goal_id: str):
    return _wrap(ec.op_execute_next_step, goal_id, _execute_call)


@app.get("/executive/goals/{goal_id}")
def get_goal(goal_id: str):
    return _wrap(ec.op_get_goal, goal_id)


@app.get("/executive/goals")
def list_goals(status: Optional[str] = None):
    return _wrap(ec.op_list_goals, status)
