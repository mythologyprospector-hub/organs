"""
executive_core.py — the goal-driven, multi-step action organ. The first
thing in this system that can chain calls across other organs on its
own, which is exactly why it's built the most conservatively.

WHAT THIS DOES NOT DO, on purpose: it does not use an LLM to
autonomously turn a vague goal into a plan. Given what's already been
established about local model quality, promising autonomous planning
would be dishonest. What it DOES do is real: track a goal, hold an
EXPLICIT plan (a human or another process submits the actual steps),
route every single step through Critic before it can run, and refuse to
execute anything Critic flags without an explicit human approval first.
Autonomous planning is a real future capability — layered on top of
this skeleton later, not assumed now.

The lifecycle:
    goal created (status: draft)
      -> plan submitted as an explicit ordered list of steps
      -> EVERY step gets classified by Critic before anything runs
      -> safe/reversible steps can execute automatically
      -> caution/high_risk steps HALT and wait for a human decision —
         no default, no timeout-based auto-approval, no exception
      -> steps execute in order; a failed step stops the goal rather
         than silently continuing past a problem
      -> goal ends: completed, failed, or blocked (waiting on a human)

Same DI pattern as Reflection: the actual HTTP calls (to Critic, to
whatever organ a step targets) are injected, not hardcoded — so all the
state-machine logic (ordering, gating, failure handling) is fully
tested without a real network anywhere nearby.
"""
import json
import os
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("EXECUTIVE_DATA_DIR", str(HERE / "data"))).expanduser()
GOALS_PATH = DATA_DIR / "goals.jsonl"

VALID_GOAL_STATUS = {"draft", "awaiting_approval", "ready", "executing", "completed", "failed", "blocked"}
VALID_STEP_STATUS = {"pending_approval", "approved", "rejected", "executing", "succeeded", "failed", "skipped"}


class ExecutiveError(Exception):
    pass


def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not GOALS_PATH.exists():
        GOALS_PATH.touch()


def _load_all():
    """Skips any trailing line that fails to parse as JSON — e.g. a
    process killed mid-write leaving a truncated final line — rather
    than letting one bad line take down every operation in this organ.
    Same defense applied to the equivalent case in reflection_core's
    load_history() and memory_core's load_jsonl()/op_list(); this one
    matters more than most, since a crash here doesn't just lose a
    read, it can strand a goal mid-flight waiting on a human approval
    that this organ would otherwise have no way to surface."""
    ensure_data_dir()
    if not GOALS_PATH.exists():
        return []
    out = []
    for line in GOALS_PATH.read_text(encoding="utf-8").strip().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _save_all(goals):
    ensure_data_dir()
    with GOALS_PATH.open("w", encoding="utf-8") as f:
        for g in goals:
            f.write(json.dumps(g) + "\n")


def _find(goals, goal_id):
    for g in goals:
        if g["id"] == goal_id:
            return g
    return None


def op_create_goal(description: str, created_by: str = "user"):
    if not description or not description.strip():
        raise ExecutiveError("description must not be empty")
    goal = {
        "id": uuid.uuid4().hex[:12],
        "description": description,
        "created_by": created_by,
        "created_ts": time.time(),
        "status": "draft",
        "steps": [],
    }
    goals = _load_all()
    goals.append(goal)
    _save_all(goals)
    return goal


def op_submit_plan(goal_id: str, steps: list, evaluate_risk):
    """`steps` is an explicit, ordered list of
    {organ, method, path, body, description}. `evaluate_risk(organ,
    method, path, body)` is injected — the real implementation calls
    Critic over HTTP; tests inject a fake. Every step gets classified
    NOW, at submission time, not at execution time — so the whole plan's
    risk profile is visible before anything runs."""
    if not steps:
        raise ExecutiveError("a plan needs at least one step")

    goals = _load_all()
    goal = _find(goals, goal_id)
    if goal is None:
        raise ExecutiveError(f"no goal with id {goal_id!r}")
    if goal["status"] != "draft":
        raise ExecutiveError(f"goal {goal_id!r} already has a plan (status={goal['status']!r})")

    built_steps = []
    any_needs_approval = False
    for i, step in enumerate(steps):
        for required in ("organ", "method", "path"):
            if required not in step:
                raise ExecutiveError(f"step {i} is missing required field {required!r}")

        risk = evaluate_risk(step["organ"], step["method"], step["path"], step.get("body"))
        needs_approval = risk.get("requires_human_approval", True)  # fail closed if Critic's response is malformed
        any_needs_approval = any_needs_approval or needs_approval

        built_steps.append({
            "id": uuid.uuid4().hex[:8],
            "index": i,
            "organ": step["organ"], "method": step["method"], "path": step["path"],
            "body": step.get("body"), "description": step.get("description", ""),
            "risk_tier": risk.get("risk_tier", "high_risk"),
            "risk_reasoning": risk.get("reasoning", ""),
            "requires_human_approval": needs_approval,
            "status": "pending_approval" if needs_approval else "approved",
            "result": None,
        })

    goal["steps"] = built_steps
    goal["status"] = "awaiting_approval" if any_needs_approval else "ready"
    _save_all(goals)
    return goal


def op_approve_step(goal_id: str, step_id: str, approved_by: str = "user"):
    goals = _load_all()
    goal = _find(goals, goal_id)
    if goal is None:
        raise ExecutiveError(f"no goal with id {goal_id!r}")
    step = next((s for s in goal["steps"] if s["id"] == step_id), None)
    if step is None:
        raise ExecutiveError(f"no step with id {step_id!r} on goal {goal_id!r}")
    if step["status"] != "pending_approval":
        raise ExecutiveError(f"step {step_id!r} is not awaiting approval (status={step['status']!r})")

    step["status"] = "approved"
    step["approved_by"] = approved_by
    step["approved_ts"] = time.time()

    if all(s["status"] in ("approved", "succeeded", "skipped") for s in goal["steps"]):
        goal["status"] = "ready"
    _save_all(goals)
    return step


def op_reject_step(goal_id: str, step_id: str, reason: str = ""):
    goals = _load_all()
    goal = _find(goals, goal_id)
    if goal is None:
        raise ExecutiveError(f"no goal with id {goal_id!r}")
    step = next((s for s in goal["steps"] if s["id"] == step_id), None)
    if step is None:
        raise ExecutiveError(f"no step with id {step_id!r} on goal {goal_id!r}")
    if step["status"] != "pending_approval":
        raise ExecutiveError(f"step {step_id!r} is not awaiting approval (status={step['status']!r})")

    step["status"] = "rejected"
    step["reject_reason"] = reason
    goal["status"] = "blocked"
    _save_all(goals)
    return step


def op_execute_next_step(goal_id: str, execute_call):
    """`execute_call(organ, method, path, body)` is injected — the real
    implementation discovers the organ via the registry and makes the
    actual HTTP call; tests inject a fake. Executes exactly ONE step per
    call — the caller decides whether to keep calling this in a loop.
    Never executes past a step that isn't approved, and never continues
    past a failure automatically."""
    goals = _load_all()
    goal = _find(goals, goal_id)
    if goal is None:
        raise ExecutiveError(f"no goal with id {goal_id!r}")
    if not goal["steps"]:
        raise ExecutiveError(f"goal {goal_id!r} has no plan yet")

    next_step = None
    for step in sorted(goal["steps"], key=lambda s: s["index"]):
        if step["status"] in ("succeeded", "skipped"):
            continue
        next_step = step
        break

    if next_step is None:
        goal["status"] = "completed"
        _save_all(goals)
        return {"goal_id": goal_id, "done": True, "goal_status": "completed"}

    if next_step["status"] == "pending_approval":
        goal["status"] = "awaiting_approval"
        _save_all(goals)
        return {"goal_id": goal_id, "done": False, "goal_status": "awaiting_approval",
                "blocked_on_step": next_step["id"], "reason": "step requires human approval"}

    if next_step["status"] == "rejected":
        goal["status"] = "blocked"
        _save_all(goals)
        return {"goal_id": goal_id, "done": False, "goal_status": "blocked",
                "blocked_on_step": next_step["id"], "reason": "step was rejected"}

    if next_step["status"] != "approved":
        raise ExecutiveError(f"step {next_step['id']!r} is in an unexpected state {next_step['status']!r}")

    # actually run it
    next_step["status"] = "executing"
    goal["status"] = "executing"
    _save_all(goals)

    try:
        result = execute_call(next_step["organ"], next_step["method"], next_step["path"], next_step.get("body"))
        next_step["status"] = "succeeded"
        next_step["result"] = result
        next_step["executed_ts"] = time.time()
        outcome = {"goal_id": goal_id, "done": False, "goal_status": "executing",
                   "step_id": next_step["id"], "step_status": "succeeded", "result": result}
    except Exception as e:
        next_step["status"] = "failed"
        next_step["result"] = {"error": str(e)}
        next_step["executed_ts"] = time.time()
        goal["status"] = "failed"  # a failed step stops the goal, doesn't cascade silently
        outcome = {"goal_id": goal_id, "done": True, "goal_status": "failed",
                   "step_id": next_step["id"], "step_status": "failed", "error": str(e)}

    goals2 = _load_all()
    goal2 = _find(goals2, goal_id)
    goal2["steps"] = goal["steps"]
    goal2["status"] = goal["status"]
    _save_all(goals2)

    return outcome


def op_get_goal(goal_id: str):
    goal = _find(_load_all(), goal_id)
    if goal is None:
        raise ExecutiveError(f"no goal with id {goal_id!r}")
    return goal


def op_list_goals(status: str = None):
    goals = _load_all()
    if status:
        goals = [g for g in goals if g["status"] == status]
    return goals
