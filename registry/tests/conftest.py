import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))


@pytest.fixture
def rc(tmp_path, monkeypatch):
    """registry_core loads its snapshot EAGERLY at module import time
    (unlike every other organ, which loads lazily inside functions) —
    so isolating tests means setting env vars BEFORE the reload, and the
    reload itself re-runs that eager load against the fresh, empty tmp
    dir."""
    monkeypatch.setenv("REGISTRY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REGISTRY_STALE_AFTER", "30")
    import registry_core
    importlib.reload(registry_core)
    yield registry_core


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("REGISTRY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REGISTRY_STALE_AFTER", "30")

    import registry_core
    importlib.reload(registry_core)
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
