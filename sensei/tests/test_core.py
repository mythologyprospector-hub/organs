import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import sensei_core as sc


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(sc, "HISTORY_PATH", tmp_path / "history.jsonl")
    monkeypatch.setattr(sc, "SEEN_CHAINS_PATH", tmp_path / "seen_chains.json")
    yield


def test_default_mode_is_watching():
    state = sc.load_state()
    assert state["mode"] == "watching"


def test_set_mode_to_ready():
    state = sc.op_set_mode("ready")
    assert state["mode"] == "ready"
    assert state["mode_changed_ts"] is not None


def test_set_mode_rejects_unknown_mode():
    with pytest.raises(sc.SenseiError):
        sc.op_set_mode("sleeping")


def test_set_mode_noop_when_already_that_mode():
    sc.op_set_mode("ready")
    state = sc.load_state()
    ts_before = state["mode_changed_ts"]
    state2 = sc.op_set_mode("ready")
    assert state2["mode_changed_ts"] == ts_before


def test_nudge_suppressed_while_watching():
    delivered = []
    result = sc.op_nudge("shell", "want an alias for this?", "shell_watcher",
                          deliver_fn=lambda m: delivered.append(m))
    assert result["delivered"] is False
    assert result["suppressed"] is True
    assert delivered == []  # never called deliver_fn at all


def test_nudge_delivered_while_ready():
    sc.op_set_mode("ready")
    delivered = []
    result = sc.op_nudge("shell", "want an alias for this?", "shell_watcher",
                          deliver_fn=lambda m: delivered.append(m))
    assert result["delivered"] is True
    assert delivered == ["want an alias for this?"]


def test_suppressed_nudges_never_batch_deliver_on_unmute():
    """The core requirement: flipping to ready must not release a
    backlog of nudges that were generated while watching."""
    delivered = []
    sc.op_nudge("shell", "nudge one", "shell_watcher", deliver_fn=lambda m: delivered.append(m))
    sc.op_nudge("shell", "nudge two", "shell_watcher", deliver_fn=lambda m: delivered.append(m))
    assert delivered == []

    sc.op_set_mode("ready")
    # nothing about flipping mode itself should call deliver_fn
    assert delivered == []

    history = sc.load_history(n=10)
    assert len(history) == 2
    assert all(h["delivered"] is False for h in history)


def test_nudge_rejects_empty_message():
    with pytest.raises(sc.SenseiError):
        sc.op_nudge("shell", "   ", "shell_watcher")


def test_history_newest_first_and_respects_n():
    sc.op_set_mode("ready")
    for i in range(5):
        sc.op_nudge("shell", f"nudge {i}", "shell_watcher", deliver_fn=lambda m: None)
    history = sc.load_history(n=3)
    assert len(history) == 3
    assert history[0]["message"] == "nudge 4"


def test_history_delivered_only_filter():
    sc.op_nudge("shell", "suppressed one", "shell_watcher")  # watching, suppressed
    sc.op_set_mode("ready")
    sc.op_nudge("shell", "delivered one", "shell_watcher", deliver_fn=lambda m: None)

    all_history = sc.load_history(n=10)
    delivered_history = sc.load_history(n=10, delivered_only=True)
    assert len(all_history) == 2
    assert len(delivered_history) == 1
    assert delivered_history[0]["message"] == "delivered one"


def test_history_skips_corrupt_trailing_line(tmp_path):
    sc.op_nudge("shell", "good entry", "shell_watcher")
    with sc.HISTORY_PATH.open("a") as f:
        f.write("{not valid json\n")
    history = sc.load_history(n=10)
    assert len(history) == 1
    assert history[0]["message"] == "good entry"


def test_get_status_reports_nudge_count():
    sc.op_set_mode("ready")
    sc.op_nudge("shell", "one", "shell_watcher", deliver_fn=lambda m: None)
    sc.op_nudge("shell", "two", "shell_watcher", deliver_fn=lambda m: None)
    status = sc.op_get_status()
    assert status["nudge_count"] == 2
    assert status["mode"] == "ready"


def test_record_response_shape():
    result = sc.op_record_response(nudge_ts=12345.0, accepted=True)
    assert result["nudge_ts"] == 12345.0
    assert result["accepted"] is True
    assert "ts" in result


def test_state_survives_corrupt_json(tmp_path):
    sc.STATE_PATH.write_text("{not json")
    state = sc.load_state()
    assert state["mode"] == "watching"  # falls back to default cleanly


def test_seen_chain_starts_unsuggested():
    assert sc.op_has_suggested_chain("some-key") is False


def test_mark_chain_suggested_then_has_suggested_true():
    sc.op_mark_chain_suggested("chain-abc", "want an alias for this chain?")
    assert sc.op_has_suggested_chain("chain-abc") is True


def test_mark_chain_suggested_is_independent_per_key():
    sc.op_mark_chain_suggested("chain-abc", "message a")
    assert sc.op_has_suggested_chain("chain-xyz") is False


def test_forget_chain_removes_it():
    sc.op_mark_chain_suggested("chain-abc", "message a")
    assert sc.op_forget_chain("chain-abc") is True
    assert sc.op_has_suggested_chain("chain-abc") is False


def test_forget_chain_returns_false_when_not_tracked():
    assert sc.op_forget_chain("never-seen") is False


def test_seen_chains_survive_corrupt_json(tmp_path):
    sc.SEEN_CHAINS_PATH.write_text("{not json")
    # ensure_files only creates it if missing, so a corrupt existing file
    # needs _load_seen_chains itself to fall back cleanly rather than crash.
    assert sc.op_has_suggested_chain("anything") is False
