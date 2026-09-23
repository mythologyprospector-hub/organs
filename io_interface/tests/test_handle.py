def safe_risk(*a, **k):
    return {"risk_tier": "safe", "requires_human_approval": False, "reasoning": "test"}


def risky_risk(*a, **k):
    return {"risk_tier": "high_risk", "requires_human_approval": True, "reasoning": "test"}


def ok_execute(*a, **k):
    return {"ok": True}


def failing_execute(*a, **k):
    raise RuntimeError("target unreachable")


def fake_goal(*a, **k):
    return {"id": "fakegoal123", "status": "awaiting_approval"}


def test_unmatched_text_never_reaches_execution(ioc):
    calls = {"risk": 0, "execute": 0, "goal": 0}

    def tracking_risk(*a, **k):
        calls["risk"] += 1
        return safe_risk()

    def tracking_execute(*a, **k):
        calls["execute"] += 1
        return ok_execute()

    def tracking_goal(*a, **k):
        calls["goal"] += 1
        return fake_goal()

    result = ioc.op_handle("nonsense request", tracking_risk, tracking_execute, tracking_goal)
    assert result["action_taken"] is False
    assert calls == {"risk": 0, "execute": 0, "goal": 0}  # never even asked Critic


def test_safe_action_executes_directly(ioc):
    result = ioc.op_handle("memory stats", safe_risk, ok_execute, fake_goal)
    assert result["action_taken"] is True
    assert result["result"] == {"ok": True}
    assert "needs_approval" not in result


def test_risky_action_creates_goal_instead_of_executing(ioc):
    calls = {"execute": 0}

    def tracking_execute(*a, **k):
        calls["execute"] += 1
        return ok_execute()

    result = ioc.op_handle("restart ollama", risky_risk, tracking_execute, fake_goal)
    assert result["action_taken"] is False
    assert result["needs_approval"] is True
    assert result["goal"]["id"] == "fakegoal123"
    assert calls["execute"] == 0  # never ran it directly


def test_execution_failure_reported_not_crashed(ioc):
    result = ioc.op_handle("memory stats", safe_risk, failing_execute, fake_goal)
    assert result["action_taken"] is False
    assert "error" in result
    assert "unreachable" in result["error"]


def test_interpreted_action_always_shown_regardless_of_outcome(ioc):
    """Transparency requirement: whatever was inferred must always be
    visible in the response, whether it ran, failed, or needed approval."""
    for risk_fn in (safe_risk, risky_risk):
        result = ioc.op_handle("remember that testing matters", risk_fn, ok_execute, fake_goal)
        assert result["interpreted_as"]["intent"] == "memory_add"
        assert result["interpreted_as"]["organ"] == "memory"


def test_malformed_risk_response_fails_closed_to_goal_creation(ioc):
    def broken_risk(*a, **k):
        return {}  # no requires_human_approval field at all

    calls = {"execute": 0, "goal": 0}

    def tracking_execute(*a, **k):
        calls["execute"] += 1

    def tracking_goal(*a, **k):
        calls["goal"] += 1
        return fake_goal()

    result = ioc.op_handle("memory stats", broken_risk, tracking_execute, tracking_goal)
    assert calls["execute"] == 0
    assert calls["goal"] == 1
    assert result["needs_approval"] is True
