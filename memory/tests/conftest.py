import hashlib
import importlib
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))

FAKE_DIM = 8


def _fake_vector(text: str):
    """Deterministic pseudo-embedding: identical text -> identical vector,
    different text -> (almost certainly) different vector. Good enough to
    test duplicate-detection and storage; NOT meant to carry real semantic
    meaning, so tests never assert on which of two *different* texts is
    'more similar' — only on identical-text duplicate detection and on
    compute_salience/compute_confidence directly for ranking logic."""
    digest = hashlib.md5(text.encode("utf-8")).digest()
    floats = struct.unpack("8B", digest[:8])
    return [f / 255.0 for f in floats]


def _fake_embed(text, model=None, timeout=30.0, retries=1):
    return _fake_vector(text)


def _fake_generate(prompt, model=None, timeout=90.0, retries=1):
    return f"[distilled from {len(prompt)} chars of notes]"


@pytest.fixture
def mc(tmp_path, monkeypatch):
    """A freshly-imported memory_core pointed at an isolated tmp data dir,
    with Ollama calls faked out. Every test gets a clean slate."""
    monkeypatch.setenv("LLAMA_MEMORY_DIR", str(tmp_path / "data"))
    import memory_core
    importlib.reload(memory_core)
    monkeypatch.setattr(memory_core, "ollama_embed", _fake_embed)
    monkeypatch.setattr(memory_core, "ollama_generate", _fake_generate)
    yield memory_core


@pytest.fixture
def broken_ollama_mc(tmp_path, monkeypatch):
    """Same, but Ollama calls raise MemoryError — for testing the
    'Ollama's down' path explicitly."""
    monkeypatch.setenv("LLAMA_MEMORY_DIR", str(tmp_path / "data"))
    import memory_core
    importlib.reload(memory_core)

    def _raise_embed(text, model=None, timeout=30.0, retries=1):
        raise memory_core.MemoryError("Could not reach Ollama at http://fake (connection refused)")

    monkeypatch.setattr(memory_core, "ollama_embed", _raise_embed)
    yield memory_core


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    """A TestClient wired to a fresh main.py + memory_core, isolated data
    dir, faked Ollama calls. Proves the HTTP layer, not just the core."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("LLAMA_MEMORY_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEMORY_BASE_URL", "http://localhost:8001")
    # organ_client.py reads ORGAN_REGISTRY_URL into a module-level constant
    # the FIRST time it's imported in this process (see organ_client.py) —
    # so this has to be set before `import main` ever runs, not just before
    # this fixture. Pointed at a guaranteed-dead address so tests can never
    # register into, heartbeat to, or discover through whatever real
    # Registry happens to be live on the default port on this machine.
    monkeypatch.setenv("ORGAN_REGISTRY_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ORGAN_TELEMETRY_ENABLED", "0")

    import memory_core
    importlib.reload(memory_core)
    monkeypatch.setattr(memory_core, "ollama_embed", _fake_embed)
    monkeypatch.setattr(memory_core, "ollama_generate", _fake_generate)

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
