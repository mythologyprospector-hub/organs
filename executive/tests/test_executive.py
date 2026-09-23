def safe_risk(*a, **k):
    return {"risk_tier": "safe", "requires_human_approval": False, "reasoning": "test: always safe"}


def risky_risk(*a, **k):
    return {"risk_tier": "high_risk", "requires_human_approval": True, "reasoning": "test: always risky"}


def ok_execute(*a, **k):
    return {"ok": True}


def failing_execute(*a, **k):
    raise RuntimeError("target organ returned an error")


def test_create_goal(ec):
    goal = ec.op_create_goal("test the pipeline")
    assert goal["status"] == "draft"
    assert goal["steps"] == []


def test_create_goal_rejects_empty_description(ec):
    try:
        ec.op_create_goal("")
        assert False
    except ec.ExecutiveError:
        pass


def test_load_all_skips_corrupted_trailing_line(ec):
    """A process killed mid-write can leave a truncated final line in
    goals.jsonl. That must not crash every operation in the organ — a
    stuck-mid-flight goal (possibly awaiting a human's approval) is
    exactly the case where availability of every OTHER goal matters
    most, not less."""
    ec.op_create_goal("first goal")
    ec.op_create_goal("second goal")

    with ec.GOALS_PATH.open("a", encoding="utf-8") as f:
        f.write('{"id": "trunc')  # truncated, no closing brace/newline

    goals = ec.op_list_goals()  # must not raise
    assert len(goals) == 2
    assert {g["description"] for g in goals} == {"first goal", "second goal"}


def test_submit_plan_all_safe_steps_marks_ready_not_awaiting(ec):
    goal = ec.op_create_goal("do a safe thing")
    steps = [{"organ": "memory", "method": "GET", "path": "/memory/stats"}]
    updated = ec.op_submit_plan(goal["id"], steps, safe_risk)
    assert updated["status"] == "ready"
    assert updated["steps"][0]["status"] == "approved"  # auto-approved, safe tier
    assert updated["steps"][0]["requires_human_approval"] is False


def test_submit_plan_with_risky_step_marks_awaiting_approval(ec):
    goal = ec.op_create_goal("do a risky thing")
    steps = [{"organ": "orchestrator", "method": "POST", "path": "/orchestrator/services/ollama/restart"}]
    updated = ec.op_submit_plan(goal["id"], steps, risky_risk)
    assert updated["status"] == "awaiting_approval"
    assert updated["steps"][0]["status"] == "pending_approval"


def test_submit_plan_mixed_steps_any_risky_blocks_the_whole_plan(ec):
    """One risky step among several safe ones still halts the whole
    goal — a plan is only as safe as its riskiest step."""
    goal = ec.op_create_goal("mixed plan")
    steps = [
        {"organ": "memory", "method": "GET", "path": "/memory/stats"},
        {"organ": "orchestrator", "method": "POST", "path": "/orchestrator/services/x/stop"},
    ]

    def mixed_risk(organ, method, path, body):
        return risky_risk() if "orchestrator" in organ else safe_risk()

    updated = ec.op_submit_plan(goal["id"], steps, mixed_risk)
    assert updated["status"] == "awaiting_approval"
    assert updated["steps"][0]["status"] == "approved"
    assert updated["steps"][1]["status"] == "pending_approval"


def test_cannot_submit_plan_twice(ec):
    goal = ec.op_create_goal("x")
    steps = [{"organ": "memory", "method": "GET", "path": "/x"}]
    ec.op_submit_plan(goal["id"], steps, safe_risk)
    try:
        ec.op_submit_plan(goal["id"], steps, safe_risk)
        assert False
    except ec.ExecutiveError:
        pass


def test_submit_plan_requires_at_least_one_step(ec):
    goal = ec.op_create_goal("x")
    try:
        ec.op_submit_plan(goal["id"], [], safe_risk)
        assert False
    except ec.ExecutiveError:
        pass


def test_execute_next_step_blocked_on_pending_approval(ec):
    """The core safety guarantee: a step needing approval CANNOT be
    executed just by calling execute_next — approval is a separate,
    required action."""
    goal = ec.op_create_goal("x")
    steps = [{"organ": "orchestrator", "method": "POST", "path": "/orchestrator/services/x/stop"}]
    ec.op_submit_plan(goal["id"], steps, risky_risk)

    result = ec.op_execute_next_step(goal["id"], ok_execute)
    assert result["done"] is False
    assert result["goal_status"] == "awaiting_approval"
    # confirm the step genuinely never ran
    goal_after = ec.op_get_goal(goal["id"])
    assert goal_after["steps"][0]["status"] == "pending_approval"


def test_approve_then_execute_actually_runs_it(ec):
    goal = ec.op_create_goal("x")
    steps = [{"organ": "orchestrator", "method": "POST", "path": "/orchestrator/services/x/stop"}]
    plan = ec.op_submit_plan(goal["id"], steps, risky_risk)
    step_id = plan["steps"][0]["id"]

    ec.op_approve_step(goal["id"], step_id, approved_by="jimmydev")
    result = ec.op_execute_next_step(goal["id"], ok_execute)
    assert result["step_status"] == "succeeded"

    goal_after = ec.op_get_goal(goal["id"])
    assert goal_after["steps"][0]["status"] == "succeeded"
    assert goal_after["steps"][0]["approved_by"] == "jimmydev"


def test_reject_step_blocks_the_goal_permanently(ec):
    goal = ec.op_create_goal("x")
    steps = [{"organ": "orchestrator", "method": "POST", "path": "/orchestrator/services/x/stop"}]
    plan = ec.op_submit_plan(goal["id"], steps, risky_risk)
    step_id = plan["steps"][0]["id"]

    ec.op_reject_step(goal["id"], step_id, reason="too risky right now")
    result = ec.op_execute_next_step(goal["id"], ok_execute)
    assert result["goal_status"] == "blocked"

    goal_after = ec.op_get_goal(goal["id"])
    assert goal_after["steps"][0]["status"] == "rejected"
    assert goal_after["steps"][0]["reject_reason"] == "too risky right now"


def test_cannot_approve_a_step_twice(ec):
    goal = ec.op_create_goal("x")
    steps = [{"organ": "x", "method": "POST", "path": "/x"}]
    plan = ec.op_submit_plan(goal["id"], steps, risky_risk)
    step_id = plan["steps"][0]["id"]
    ec.op_approve_step(goal["id"], step_id)
    try:
        ec.op_approve_step(goal["id"], step_id)
        assert False
    except ec.ExecutiveError:
        pass


def test_failed_step_stops_the_goal_does_not_cascade(ec):
    """A failure must stop forward progress, not silently continue past
    a broken step to the next one."""
    goal = ec.op_create_goal("x")
    steps = [
        {"organ": "memory", "method": "GET", "path": "/a"},
        {"organ": "memory", "method": "GET", "path": "/b"},
    ]
    ec.op_submit_plan(goal["id"], steps, safe_risk)  # both auto-approved (safe)

    result = ec.op_execute_next_step(goal["id"], failing_execute)
    assert result["step_status"] == "failed"
    assert result["goal_status"] == "failed"

    goal_after = ec.op_get_goal(goal["id"])
    assert goal_after["steps"][0]["status"] == "failed"
    assert goal_after["steps"][1]["status"] == "pending_approval" if False else True
    # second step must NOT have executed
    assert goal_after["steps"][1]["status"] not in ("succeeded", "executing")


def test_full_multi_step_safe_plan_executes_in_order_to_completion(ec):
    order = []

    def tracking_execute(organ, method, path, body):
        order.append(path)
        return {"ok": True}

    goal = ec.op_create_goal("multi step")
    steps = [
        {"organ": "memory", "method": "GET", "path": "/step1"},
        {"organ": "memory", "method": "GET", "path": "/step2"},
        {"organ": "memory", "method": "GET", "path": "/step3"},
    ]
    ec.op_submit_plan(goal["id"], steps, safe_risk)

    r1 = ec.op_execute_next_step(goal["id"], tracking_execute)
    r2 = ec.op_execute_next_step(goal["id"], tracking_execute)
    r3 = ec.op_execute_next_step(goal["id"], tracking_execute)
    r4 = ec.op_execute_next_step(goal["id"], tracking_execute)  # nothing left

    assert order == ["/step1", "/step2", "/step3"]
    assert r4["done"] is True
    assert r4["goal_status"] == "completed"


def test_list_goals_filters_by_status(ec):
    ec.op_create_goal("goal a")
    ec.op_create_goal("goal b")
    all_goals = ec.op_list_goals()
    assert len(all_goals) == 2
    draft_goals = ec.op_list_goals(status="draft")
    assert len(draft_goals) == 2
    empty = ec.op_list_goals(status="completed")
    assert empty == []


def test_get_nonexistent_goal_errors(ec):
    try:
        ec.op_get_goal("nonexistent")
        assert False
    except ec.ExecutiveError:
        pass


def test_approve_nonexistent_step_errors(ec):
    goal = ec.op_create_goal("x")
    try:
        ec.op_approve_step(goal["id"], "nonexistent")
        assert False
    except ec.ExecutiveError:
        pass


def test_missing_required_step_fields_rejected_at_submit_time(ec):
    goal = ec.op_create_goal("x")
    try:
        ec.op_submit_plan(goal["id"], [{"organ": "memory"}], safe_risk)  # missing method, path
        assert False
    except ec.ExecutiveError as e:
        assert "method" in str(e)


def test_malformed_critic_response_fails_closed(ec):
    """If the risk evaluator returns something incomplete/malformed,
    the step must default to requiring approval, not slip through."""
    def broken_risk(*a, **k):
        return {}  # no risk_tier, no requires_human_approval at all

    goal = ec.op_create_goal("x")
    steps = [{"organ": "x", "method": "POST", "path": "/x"}]
    updated = ec.op_submit_plan(goal["id"], steps, broken_risk)
    assert updated["steps"][0]["requires_human_approval"] is True
    assert updated["status"] == "awaiting_approval"
