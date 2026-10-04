"""Contract tests for the Organs -> Renaissance semantic handoff seam."""

from io_interface_core import op_handle, op_interpret


def test_operational_catalog_wins_before_renaissance_handoff():
    calls = []

    def handoff(text):
        calls.append(text)
        return {"expression": text, "disposition": "capability_request", "capability": "learn", "mode": "answer"}

    result = op_interpret("memory stats", handoff)
    assert result["matched"] is True
    assert result["organ"] == "memory"
    assert calls == []


def test_non_operational_expression_reaches_renaissance_handoff():
    text = "I want to learn how to read a Linux process map."

    def handoff(received):
        assert received == text
        return {"expression": received, "disposition": "capability_request", "capability": "learn", "mode": "answer"}

    result = op_interpret(text, handoff)
    assert result["expression"] == text
    assert result["disposition"] == "capability_request"
    assert result["capability"] == "learn"
    assert result["mode"] == "answer"


def test_handoff_result_cannot_execute_or_authorize():
    text = "Something is wrong with this."

    def handoff(received):
        return {
            "expression": received,
            "disposition": "clarify",
            "authorized": False,
            "evidence": False,
            "executed": False,
        }

    result = op_handle(
        text,
        lambda *_: (_ for _ in ()).throw(AssertionError("risk gate must not run")),
        lambda *_: (_ for _ in ()).throw(AssertionError("execution must not run")),
        lambda *_: (_ for _ in ()).throw(AssertionError("approval must not run")),
        handoff,
    )

    assert result["action_taken"] is False
    assert result["renaissance"]["disposition"] == "clarify"
