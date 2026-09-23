import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))


@pytest.fixture
def sc(tmp_path, monkeypatch):
    monkeypatch.setenv("SENSEI_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("SENSEI_HISTORY_PATH", str(tmp_path / "history.jsonl"))
    monkeypatch.setenv("SENSEI_SEEN_CHAINS_PATH", str(tmp_path / "seen_chains.json"))
    import sensei_core
    importlib.reload(sensei_core)
    yield sensei_core


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("SENSEI_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("SENSEI_HISTORY_PATH", str(tmp_path / "history.jsonl"))
    monkeypatch.setenv("SENSEI_SEEN_CHAINS_PATH", str(tmp_path / "seen_chains.json"))
    monkeypatch.setenv("SENSEI_BASE_URL", "http://localhost:8012")
    # Guaranteed-dead address so attach_to_registry's boot-time attempt
    # fails fast and quietly instead of hanging or hitting a real registry.
    monkeypatch.setenv("ORGAN_REGISTRY_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ORGAN_TELEMETRY_ENABLED", "0")

    import sensei_core
    importlib.reload(sensei_core)
    import main
    importlib.reload(main)

    import organ_base
    monkeypatch.setattr(organ_base, "_ask_critic",
                         lambda organ, method, path, body: ("safe", "test fixture bypasses risk gate"))

    with TestClient(main.app) as client:
        yield client
