import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))


@pytest.fixture
def ic(monkeypatch):
    import introspection_core
    importlib.reload(introspection_core)
    introspection_core.clear_cache()
    yield introspection_core


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.responses = {}
        self.default = (127, "", "command not found")

    def __call__(self, cmd, timeout=8):
        self.calls.append(tuple(cmd))
        return self.responses.get(tuple(cmd), self.default)


@pytest.fixture
def fake_runner(ic, monkeypatch):
    runner = FakeRunner()
    monkeypatch.setattr(ic, "_run", runner)
    return runner


@pytest.fixture
def fake_files(ic, monkeypatch):
    """Lets tests script what _read_file returns for specific paths."""
    contents = {}

    def fake_read(path):
        return contents.get(path, "")

    monkeypatch.setattr(ic, "_read_file", fake_read)
    return contents


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("INTROSPECT_BASE_URL", "http://localhost:8005")
    # Guaranteed-dead address — see memory/tests/conftest.py for why this
    # has to be set before `import main`, not just before this fixture.
    monkeypatch.setenv("ORGAN_REGISTRY_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ORGAN_TELEMETRY_ENABLED", "0")

    import introspection_core
    importlib.reload(introspection_core)
    introspection_core.clear_cache()
    import main
    importlib.reload(main)

    runner = FakeRunner()
    monkeypatch.setattr(main.ic, "_run", runner)

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
