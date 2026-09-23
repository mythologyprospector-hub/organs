import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))


@pytest.fixture
def sc(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_WORKSPACE_ROOT", str(tmp_path))
    import sandbox_core
    importlib.reload(sandbox_core)
    yield sandbox_core


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.response = (0, "", "", False)  # rc, stdout, stderr, timed_out

    def __call__(self, cmd, timeout):
        self.calls.append((tuple(cmd), timeout))
        return self.response


@pytest.fixture
def fake_runner(sc, monkeypatch):
    runner = FakeRunner()
    monkeypatch.setattr(sc, "_run", runner)
    return runner


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("SANDBOX_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("SANDBOX_BASE_URL", "http://localhost:8006")
    # Guaranteed-dead address — see memory/tests/conftest.py for why this
    # has to be set before `import main`, not just before this fixture.
    monkeypatch.setenv("ORGAN_REGISTRY_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ORGAN_TELEMETRY_ENABLED", "0")

    import sandbox_core
    importlib.reload(sandbox_core)
    import main
    importlib.reload(main)

    runner = FakeRunner()
    monkeypatch.setattr(main.sc, "_run", runner)

    import organ_base
    # These tests exercise this organ's own endpoint logic — the risk
    # gate itself has its own dedicated test suite in shared/tests/
    # test_organ_base.py, so bypass it here rather than re-testing it
    # in every organ.
    monkeypatch.setattr(organ_base, "_ask_critic",
                         lambda organ, method, path, body: ("safe", "test fixture bypasses risk gate"))

    with TestClient(main.app) as client:
        client.fake_runner = runner
        yield client
