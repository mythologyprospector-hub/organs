import importlib
import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def td(monkeypatch):
    monkeypatch.setenv("ORGAN_REGISTRY_URL", "http://registry.test")
    import tui_data
    importlib.reload(tui_data)
    yield tui_data


class FakeResponse:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen(routes: dict):
    """routes: {url_or_prefix: response_dict_or_Exception}. Matches by
    prefix so query strings (?limit=15) don't need to be spelled out.
    Handles both a plain URL string (what _get passes) and a
    urllib.request.Request object (what _post passes, since it needs
    to attach a JSON body and headers)."""
    def _urlopen(url_or_req, timeout=None):
        actual_url = url_or_req.full_url if hasattr(url_or_req, "full_url") else url_or_req
        for prefix, value in routes.items():
            if actual_url.startswith(prefix):
                if isinstance(value, Exception):
                    raise value
                return FakeResponse(value)
        raise urllib.error.URLError(f"no fake route for {actual_url}")
    return _urlopen


def test_get_returns_parsed_json_on_success(td, monkeypatch):
    monkeypatch.setattr(td.urllib.request, "urlopen", _fake_urlopen({
        "http://x/foo": {"hello": "world"},
    }))
    assert td._get("http://x/foo") == {"hello": "world"}


def test_get_returns_clean_error_never_raises(td, monkeypatch):
    monkeypatch.setattr(td.urllib.request, "urlopen", _fake_urlopen({
        "http://x/foo": urllib.error.URLError("connection refused"),
    }))
    result = td._get("http://x/foo")
    assert "error" in result
    assert "connection refused" in result["error"]


def test_fetch_registry_wraps_list_in_organs_key(td, monkeypatch):
    monkeypatch.setattr(td.urllib.request, "urlopen", _fake_urlopen({
        "http://registry.test/registry/organs": [{"name": "memory", "base_url": "http://m"}],
    }))
    result = td.fetch_registry()
    assert result == {"organs": [{"name": "memory", "base_url": "http://m"}]}


def test_fetch_registry_unreachable_returns_error(td, monkeypatch):
    monkeypatch.setattr(td.urllib.request, "urlopen", _fake_urlopen({
        "http://registry.test/registry/organs": urllib.error.URLError("refused"),
    }))
    result = td.fetch_registry()
    assert td.is_error(result)


def test_fetch_all_populates_every_organ_from_registry(td, monkeypatch):
    monkeypatch.setattr(td.urllib.request, "urlopen", _fake_urlopen({
        "http://registry.test/registry/organs": [
            {"name": "memory", "base_url": "http://mem"},
            {"name": "telemetry", "base_url": "http://tel"},
            {"name": "sandbox", "base_url": "http://sbx"},
        ],
        "http://mem/memory/stats": {"entries": 42},
        "http://tel/telemetry/stats": {"total_events": 3},
        "http://tel/telemetry/recent": [{"event_id": "abc"}],
        "http://sbx/sandbox/doctor": {"docker_available": True},
    }))
    data = td.fetch_all()
    assert data["memory"] == {"entries": 42}
    assert data["telemetry_stats"] == {"total_events": 3}
    assert data["telemetry_recent"] == [{"event_id": "abc"}]
    assert data["sandbox_doctor"] == {"docker_available": True}


def test_fetch_all_degrades_cleanly_when_registry_unreachable(td, monkeypatch):
    """The whole point: one unreachable dependency (the Registry itself,
    even) must not crash the snapshot — every other field just becomes
    its own clean 'not currently registered' error."""
    monkeypatch.setattr(td.urllib.request, "urlopen", _fake_urlopen({
        "http://registry.test/registry/organs": urllib.error.URLError("refused"),
    }))
    data = td.fetch_all()
    assert td.is_error(data["registry"])
    assert td.is_error(data["memory"])
    assert "not currently registered" in data["memory"]["error"]
    assert td.is_error(data["sandbox_doctor"])


def test_fetch_all_degrades_per_organ_not_globally(td, monkeypatch):
    """Registry is fine, memory is registered but currently unreachable
    (e.g. mid-restart) — telemetry should be completely unaffected."""
    monkeypatch.setattr(td.urllib.request, "urlopen", _fake_urlopen({
        "http://registry.test/registry/organs": [
            {"name": "memory", "base_url": "http://mem"},
            {"name": "telemetry", "base_url": "http://tel"},
        ],
        "http://mem/memory/stats": urllib.error.URLError("connection refused"),
        "http://tel/telemetry/stats": {"total_events": 0},
        "http://tel/telemetry/recent": [],
    }))
    data = td.fetch_all()
    assert td.is_error(data["memory"])
    assert not td.is_error(data["telemetry_stats"])
    assert data["telemetry_stats"] == {"total_events": 0}


def test_fetch_all_missing_organ_from_registry_is_a_clean_error(td, monkeypatch):
    """An organ simply not registered right now (never started, or
    dropped out) looks the same to a panel as one that's unreachable —
    both are 'nothing to show,' and that's the correct, honest state."""
    monkeypatch.setattr(td.urllib.request, "urlopen", _fake_urlopen({
        "http://registry.test/registry/organs": [],
    }))
    data = td.fetch_all()
    assert td.is_error(data["sandbox_doctor"])
    assert "not currently registered" in data["sandbox_doctor"]["error"]


@pytest.mark.parametrize("seconds,expected_substring", [
    (5, "s ago"),
    (90, "m ago"),
    (7200, "h ago"),
    (172800, "d ago"),
])
def test_format_age_picks_the_right_unit(td, seconds, expected_substring):
    assert expected_substring in td.format_age(seconds)


def test_format_age_handles_none(td):
    assert td.format_age(None) == "unknown"


def test_format_age_handles_garbage_input(td):
    assert td.format_age("not a number") == "unknown"


def test_is_error_true_for_error_dict(td):
    assert td.is_error({"error": "connection refused"}) is True


def test_is_error_false_for_real_data_shaped_like_a_dict(td):
    assert td.is_error({"total_events": 0, "by_source": {}}) is False


def test_is_error_false_for_a_list(td):
    assert td.is_error([{"job_id": "abc"}]) is False


def test_post_sends_real_json_body_and_returns_parsed_response(td, monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["method"] = req.get_method()
        return FakeResponse({"ok": True})

    monkeypatch.setattr(td.urllib.request, "urlopen", fake_urlopen)
    result = td._post("http://x/foo", {"text": "restart ollama"})
    assert result == {"ok": True}
    assert captured["url"] == "http://x/foo"
    assert captured["body"] == {"text": "restart ollama"}
    assert captured["method"] == "POST"


def test_post_surfaces_organs_structured_error_envelope_on_http_error(td, monkeypatch):
    """An HTTPError (e.g. a 400) still carries the target organ's own
    {"error": {...}} envelope in its body — that's more useful than the
    raw HTTP status line, so _post should parse and return it."""
    class FakeHTTPError(urllib.error.HTTPError):
        def read(self):
            return json.dumps({"error": {"code": "io_interface_error", "message": "bad input"}}).encode()

    def fake_urlopen(req, timeout=None):
        raise FakeHTTPError(req.full_url, 400, "Bad Request", {}, fp=None)

    monkeypatch.setattr(td.urllib.request, "urlopen", fake_urlopen)
    result = td._post("http://x/foo", {"text": "bad"})
    assert result == {"error": {"code": "io_interface_error", "message": "bad input"}}


def test_post_never_raises_on_connection_failure(td, monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(td.urllib.request, "urlopen", fake_urlopen)
    result = td._post("http://x/foo", {"text": "hi"})
    assert td.is_error(result)


def test_base_urls_from_registry_extracts_name_to_url_map(td):
    snapshot = {"organs": [{"name": "io_interface", "base_url": "http://io"},
                            {"name": "memory", "base_url": "http://mem"}]}
    assert td.base_urls_from_registry(snapshot) == {"io_interface": "http://io", "memory": "http://mem"}


def test_send_io_handle_calls_real_endpoint_with_real_text(td, monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse({"action_taken": True, "interpreted_as": {"intent": "restart_ollama"}})

    monkeypatch.setattr(td.urllib.request, "urlopen", fake_urlopen)
    result = td.send_io_handle("http://io", "restart ollama")
    assert captured["url"] == "http://io/io/handle"
    assert captured["body"] == {"text": "restart ollama"}
    assert result["action_taken"] is True


def test_send_io_interpret_calls_dry_run_endpoint(td, monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        return FakeResponse({"matched": True, "intent": "restart_ollama"})

    monkeypatch.setattr(td.urllib.request, "urlopen", fake_urlopen)
    result = td.send_io_interpret("http://io", "restart ollama")
    assert captured["url"] == "http://io/io/interpret"
    assert result["matched"] is True


def test_send_io_handle_without_registered_organ_returns_clean_error(td):
    result = td.send_io_handle(None, "restart ollama")
    assert td.is_error(result)
    assert "not currently registered" in result["error"]


def test_send_io_interpret_without_registered_organ_returns_clean_error(td):
    result = td.send_io_interpret(None, "restart ollama")
    assert td.is_error(result)


def test_send_executive_approve_calls_real_endpoint(td, monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse({"id": "abc123", "status": "approved"})

    monkeypatch.setattr(td.urllib.request, "urlopen", fake_urlopen)
    result = td.send_executive_approve("http://exec", "goal1", "step1", approved_by="tui")
    assert captured["url"] == "http://exec/executive/goals/goal1/steps/step1/approve"
    assert captured["body"] == {"approved_by": "tui"}
    assert result["status"] == "approved"


def test_send_executive_reject_calls_real_endpoint_with_reason(td, monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse({"id": "abc123", "status": "rejected"})

    monkeypatch.setattr(td.urllib.request, "urlopen", fake_urlopen)
    result = td.send_executive_reject("http://exec", "goal1", "step1", reason="too risky")
    assert captured["url"] == "http://exec/executive/goals/goal1/steps/step1/reject"
    assert captured["body"] == {"reason": "too risky"}
    assert result["status"] == "rejected"


def test_send_executive_approve_without_registered_organ_returns_clean_error(td):
    result = td.send_executive_approve(None, "goal1", "step1")
    assert td.is_error(result)
    assert "not currently registered" in result["error"]


def test_send_executive_reject_without_registered_organ_returns_clean_error(td):
    result = td.send_executive_reject(None, "goal1", "step1")
    assert td.is_error(result)


def test_send_executive_execute_next_calls_real_endpoint(td, monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse({"goal_id": "goal1", "done": False, "step_id": "step2", "step_status": "succeeded"})

    monkeypatch.setattr(td.urllib.request, "urlopen", fake_urlopen)
    result = td.send_executive_execute_next("http://exec", "goal1")
    assert captured["url"] == "http://exec/executive/goals/goal1/execute_next"
    assert captured["body"] == {}
    assert result["step_status"] == "succeeded"


def test_send_executive_execute_next_without_registered_organ_returns_clean_error(td):
    result = td.send_executive_execute_next(None, "goal1")
    assert td.is_error(result)


def test_fetch_live_checks_uses_only_existing_read_endpoints(td, monkeypatch):
    routes = {
        "http://registry.test/registry/organs": [
            {"name": "memory", "base_url": "http://mem"},
            {"name": "communications", "base_url": "http://comm"},
            {"name": "orchestrator", "base_url": "http://orch"},
            {"name": "reflection", "base_url": "http://refl"},
            {"name": "introspection", "base_url": "http://intro"},
            {"name": "sandbox", "base_url": "http://sbx"},
            {"name": "critic", "base_url": "http://critic"},
            {"name": "executive", "base_url": "http://exec"},
            {"name": "io_interface", "base_url": "http://io"},
            {"name": "telemetry", "base_url": "http://tel"},
        ],
        "http://mem/health": {"status": "ok"},
        "http://comm/bus/doctor": {"ok": True},
        "http://orch/orchestrator/doctor": {"ok": True},
        "http://refl/reflection/status": {"enabled": False},
        "http://intro/introspect/summary": {"host": {}},
        "http://sbx/sandbox/doctor": {"docker_available": True},
        "http://critic/critic/rules": [],
        "http://exec/executive/goals": [],
        "http://io/io/catalog": [],
        "http://tel/telemetry/stats": {"total_events": 0},
    }
    monkeypatch.setattr(td.urllib.request, "urlopen", _fake_urlopen(routes))
    registry = td.fetch_registry()
    checks = td.fetch_live_checks(registry)
    assert len(checks) == 11
    assert all(check["ok"] for check in checks)
    assert {check["organ"] for check in checks} == {
        "registry", "memory", "communications", "orchestrator", "reflection",
        "introspection", "sandbox", "critic", "executive", "io_interface",
        "telemetry",
    }


def test_fetch_live_checks_marks_missing_organs_without_raising(td, monkeypatch):
    monkeypatch.setattr(td.urllib.request, "urlopen", _fake_urlopen({
        "http://registry.test/registry/organs": [],
    }))
    registry = td.fetch_registry()
    checks = td.fetch_live_checks(registry)
    assert len(checks) == 11
    assert all(not check["ok"] for check in checks if check["organ"] != "registry")
    assert checks[0]["ok"] is True
