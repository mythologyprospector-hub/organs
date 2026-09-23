import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))


@pytest.fixture
def cc(tmp_path, monkeypatch):
    monkeypatch.setenv("COMM_DATA_DIR", str(tmp_path / "data"))
    import comm_core
    importlib.reload(comm_core)
    yield comm_core


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("COMM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("COMM_BASE_URL", "http://localhost:8002")
    # Guaranteed-dead address — see memory/tests/conftest.py for why this
    # has to be set before `import main`, not just before this fixture.
    monkeypatch.setenv("ORGAN_REGISTRY_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ORGAN_TELEMETRY_ENABLED", "0")

    import comm_core
    importlib.reload(comm_core)
    import main
    importlib.reload(main)

    import organ_base
    # These tests exercise this organ's own endpoint logic — the risk
    # gate itself has its own dedicated test suite in shared/tests/
    # test_organ_base.py, so bypass it here rather than re-testing it
    # in every organ.
    monkeypatch.setattr(organ_base, "_ask_critic",
                         lambda organ, method, path, body: ("safe", "test fixture bypasses risk gate"))

    with TestClient(main.app) as client:
        yield client
