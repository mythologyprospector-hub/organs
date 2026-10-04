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


def test_ambiguous_expression_reaches_renaissance_before_operational_execution():
    text = "Something is wrong with this."

    def handoff(received):
        assert received == text
        return {"expression": received, "disposition": "clarify"}

    result = op_interpret(text, handoff)
    assert result["expression"] == text
    assert result["disposition"] == "clarify"


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


def test_malformed_renaissance_response_fails_back_without_execution(monkeypatch):
    import io_interface.main as interface

    monkeypatch.setattr(interface, "discover", lambda name: "http://renaissance.test")
    monkeypatch.setattr(
        interface.urllib.request,
        "urlopen",
        lambda *args, **kwargs: _MalformedResponse(),
    )
    assert interface._renaissance_handoff("Can you help?") is None


class _MalformedResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b"not-json"


def test_unavailable_renaissance_fails_back_without_execution(monkeypatch):
    import io_interface.main as interface
    import urllib.error

    monkeypatch.setattr(interface, "discover", lambda name: "http://renaissance.test")

    def unavailable(*_args, **_kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(interface.urllib.request, "urlopen", unavailable)
    assert interface._renaissance_handoff("Can you help?") is None
