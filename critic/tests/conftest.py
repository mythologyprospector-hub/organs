import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))


@pytest.fixture
def cc():
    import critic_core
    yield critic_core


@pytest.fixture
def api_client(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("CRITIC_BASE_URL", "http://localhost:8007")
    # Guaranteed-dead address — see memory/tests/conftest.py for why this
    # has to be set before `import main`, not just before this fixture.
    monkeypatch.setenv("ORGAN_REGISTRY_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ORGAN_TELEMETRY_ENABLED", "0")
    import main
    with TestClient(main.app) as client:
        yield client
