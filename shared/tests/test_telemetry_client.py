import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import telemetry_client
from organ_client import RegistryError


def test_emit_returns_false_when_registry_unreachable(monkeypatch):
    def _raise(*a, **k):
        raise RegistryError("registry down")
    monkeypatch.setattr(telemetry_client, "discover", _raise)

    result = telemetry_client.emit("request", "some_organ")
    assert result is False


def test_emit_returns_false_instead_of_raising_on_unserializable_payload(monkeypatch):
    """Regression test: emit()'s own docstring promises a caller's
    successful operation must never become a failure because of
    telemetry. That covered network/availability failures already, but
    json.dumps() raising TypeError on a non-serializable payload was
    completely unguarded — it would propagate straight out of emit()
    and, since organ_base.py's middleware calls this with no try/except
    of its own, turn a genuinely successful request into an unrelated
    500. Not reachable today (the only current caller, organ_base.py's
    own middleware, always passes plain str/int payloads) but emit() is
    documented as directly callable by any organ, so this must hold
    regardless of what a future caller passes."""
    monkeypatch.setattr(telemetry_client, "discover", lambda *a, **k: "http://localhost:9999")

    class Unserializable:
        pass

    result = telemetry_client.emit("request", "some_organ", payload={"bad": Unserializable()})
    assert result is False
