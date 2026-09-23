import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import organ_base
import organ_client
from fastapi.testclient import TestClient


def _make_app(monkeypatch, register_side_effect=None):
    app = organ_base.create_organ_app("test_organ", "0.1.0", "test", ["test"])
    monkeypatch.setattr(organ_base, "_ask_critic", lambda *a, **k: ("safe", "test"))
    calls = []

    def fake_register(name, base_url, version, capabilities):
        calls.append((name, base_url, version, capabilities))
        if register_side_effect:
            register_side_effect()

    monkeypatch.setattr(organ_client, "register", fake_register)
    monkeypatch.setattr(organ_client, "HEARTBEAT_INTERVAL", 0.05)
    organ_client.attach_to_registry(app, "test_organ", "http://localhost:9999", "0.1.0", ["test"])
    return app, calls


def test_heartbeat_registers_on_startup(monkeypatch):
    app, calls = _make_app(monkeypatch)
    with TestClient(app):
        pass
    assert len(calls) >= 1
    assert calls[0] == ("test_organ", "http://localhost:9999", "0.1.0", ["test"])


def test_heartbeat_registers_repeatedly_while_running(monkeypatch):
    app, calls = _make_app(monkeypatch)
    with TestClient(app):
        import time
        time.sleep(0.2)  # several HEARTBEAT_INTERVAL (0.05s) ticks
    assert len(calls) >= 2


def test_heartbeat_task_is_cancelled_on_shutdown(monkeypatch):
    """Regression test: the heartbeat task used to have no shutdown
    handler at all — an infinite, un-cancelled asyncio task left
    scheduled on the loop for the lifetime of the process, with no
    explicit teardown when the app was asked to shut down."""
    app, calls = _make_app(monkeypatch)
    captured_task = {}

    orig_create_task = asyncio.create_task

    def spy_create_task(coro, *a, **k):
        task = orig_create_task(coro, *a, **k)
        captured_task["task"] = task
        return task

    monkeypatch.setattr(asyncio, "create_task", spy_create_task)

    with TestClient(app):
        pass

    assert "task" in captured_task
    assert captured_task["task"].cancelled() or captured_task["task"].done()


def test_register_does_not_block_the_event_loop(monkeypatch):
    """Regression test: register() is a blocking, synchronous urllib
    call. Running it directly inside the async heartbeat loop (instead
    of via asyncio.to_thread) blocked the ENTIRE event loop for however
    long that call took — meaning the organ couldn't serve any other
    request while a heartbeat check-in was in flight. This proves a
    slow register() no longer blocks a concurrent request."""
    import time

    def slow_register():
        time.sleep(0.15)  # blocking, synchronous — the whole point of this test

    app, calls = _make_app(monkeypatch, register_side_effect=slow_register)

    @app.get("/test/probe")
    def probe():
        return {"ok": True}

    with TestClient(app) as client:
        # give the startup heartbeat a moment to begin its (slow) call
        time.sleep(0.02)
        start = time.monotonic()
        response = client.get("/test/probe")
        elapsed = time.monotonic() - start

    assert response.status_code == 200
    # A blocked event loop would make this request wait out most of the
    # 0.15s sleep. Off-loop, it should return almost immediately.
    assert elapsed < 0.1


def test_registry_unreachable_at_startup_does_not_crash_the_organ(monkeypatch):
    app = organ_base.create_organ_app("test_organ", "0.1.0", "test", ["test"])
    monkeypatch.setattr(organ_base, "_ask_critic", lambda *a, **k: ("safe", "test"))

    def raising_register(*a, **k):
        raise organ_client.RegistryError("registry down")

    monkeypatch.setattr(organ_client, "register", raising_register)
    monkeypatch.setattr(organ_client, "HEARTBEAT_INTERVAL", 0.05)
    organ_client.attach_to_registry(app, "test_organ", "http://localhost:9999", "0.1.0", ["test"])

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
