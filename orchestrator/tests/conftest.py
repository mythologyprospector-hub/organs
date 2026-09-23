import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))


@pytest.fixture
def oc(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_CONFIG_PATH", str(tmp_path / "services.json"))
    import orchestrator_core
    importlib.reload(orchestrator_core)
    yield orchestrator_core


class FakeRunner:
    """Records every command and returns a scripted response for it.
    Tests set .responses[tuple(cmd)] = (rc, stdout, stderr) before
    calling into orchestrator_core, or set .default for anything not
    explicitly scripted."""

    def __init__(self):
        self.calls = []
        self.responses = {}
        self.default = (1, "", "not scripted")
        self.raise_error = None

    def __call__(self, cmd, timeout=10):
        self.calls.append(tuple(cmd))
        if self.raise_error:
            raise self.raise_error
        return self.responses.get(tuple(cmd), self.default)


@pytest.fixture
def fake_runner(oc, monkeypatch):
    runner = FakeRunner()
    monkeypatch.setattr(oc, "_run", runner)
    return runner


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("ORCH_CONFIG_PATH", str(tmp_path / "services.json"))
    monkeypatch.setenv("ORCH_BASE_URL", "http://localhost:8003")
    # Guaranteed-dead address — see memory/tests/conftest.py for why this
    # has to be set before `import main`, not just before this fixture.
    monkeypatch.setenv("ORGAN_REGISTRY_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ORGAN_TELEMETRY_ENABLED", "0")

    import orchestrator_core
    importlib.reload(orchestrator_core)
    import main
    importlib.reload(main)

    runner = FakeRunner()
    monkeypatch.setattr(main.oc, "_run", runner)

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
