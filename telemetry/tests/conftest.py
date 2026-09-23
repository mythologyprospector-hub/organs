import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))


@pytest.fixture
def tc(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEMETRY_DATA_DIR", str(tmp_path / "data"))
    import telemetry_core
    importlib.reload(telemetry_core)
    yield telemetry_core


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("TELEMETRY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TELEMETRY_BASE_URL", "http://localhost:8011")
    # Guaranteed-dead address — see memory/tests/conftest.py for why this
    # has to be set before `import main`, not just before this fixture.
    monkeypatch.setenv("ORGAN_REGISTRY_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ORGAN_TELEMETRY_ENABLED", "0")

    import telemetry_core
    importlib.reload(telemetry_core)
    import main
    importlib.reload(main)

    with TestClient(main.app) as client:
        yield client
