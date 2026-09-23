import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def watcher(tmp_path, monkeypatch):
    monkeypatch.setenv("SENSEI_SHELL_STATE_DIR", str(tmp_path))
    import shell_watcher
    import importlib
    importlib.reload(shell_watcher)
    return shell_watcher


def test_empty_command_is_skipped(watcher):
    result = watcher.process_command("   ", "/home", now=100.0)
    assert result == {"skipped": "empty_command"}


def test_self_invocation_is_skipped(watcher):
    result = watcher.process_command("python3 /srv/organs/sensei/watchers/shell_watcher.py x y", "/home", now=100.0)
    assert result == {"skipped": "self_invocation"}


def test_emits_telemetry_on_every_real_command(watcher):
    calls = []
    result = watcher.process_command(
        "ls", "/home", now=100.0,
        emit_fn=lambda cmd, cwd: calls.append((cmd, cwd)),
        nudge_fn=lambda c: None,
    )
    assert calls == [("ls", "/home")]
    assert result["nudged"] is False


def test_no_pattern_no_nudge(watcher):
    nudges = []
    watcher.process_command("ls", "/home", now=100.0, emit_fn=lambda c, w: None, nudge_fn=lambda c: nudges.append(c))
    assert nudges == []


def test_repeated_command_triggers_nudge(watcher):
    nudges = []
    kwargs = dict(emit_fn=lambda c, w: None, nudge_fn=lambda c: nudges.append(c))
    for i in range(3):
        watcher.process_command("git status", "/home", now=100.0 + i, **kwargs)
    assert len(nudges) == 1
    assert nudges[0]["kind"] == "shell_repeated_command"


def test_cooldown_prevents_second_nudge_for_same_pattern(watcher):
    nudges = []
    kwargs = dict(emit_fn=lambda c, w: None, nudge_fn=lambda c: nudges.append(c))
    for i in range(3):
        watcher.process_command("git status", "/home", now=100.0 + i, **kwargs)
    # keep running the same command — should stay in cooldown, no new nudges
    for i in range(5):
        watcher.process_command("git status", "/home", now=110.0 + i, **kwargs)
    assert len(nudges) == 1


def test_different_commands_do_not_share_buffer_growth_incorrectly(watcher):
    """Sanity check that the buffer actually accumulates real history
    across calls (state persists to disk between invocations, as it
    would across real shell commands)."""
    kwargs = dict(emit_fn=lambda c, w: None, nudge_fn=lambda c: None)
    watcher.process_command("a", "/home", now=1.0, **kwargs)
    watcher.process_command("b", "/home", now=2.0, **kwargs)
    watcher.process_command("c", "/home", now=3.0, **kwargs)

    import shell_watcher_core as core
    buffer = core.load_buffer(watcher.BUFFER_PATH)
    assert [e["cmd"] for e in buffer] == ["a", "b", "c"]


def test_process_command_survives_emit_fn_raising(watcher):
    """Telemetry being down must never prevent pattern detection —
    emit_fn failing (for any reason, not just the network exceptions
    _post() catches) must not stop the buffer from updating or a
    nudge from firing. This was a real bug: emit_fn ran before
    pattern detection with no guard, so an uncaught exception there
    killed the whole invocation silently (the bash hook redirects
    everything to /dev/null)."""
    def failing_emit(cmd, cwd):
        raise ConnectionError("telemetry is down")

    nudges = []
    kwargs = dict(emit_fn=failing_emit, nudge_fn=lambda c: nudges.append(c))
    for i in range(3):
        watcher.process_command("git status", "/home", now=100.0 + i, **kwargs)
    assert len(nudges) == 1  # detection and nudging still worked despite emit_fn always raising


def test_concurrent_invocations_do_not_lose_updates(watcher, tmp_path):
    """Regression test for the race that caused the real-world failure:
    several near-simultaneous invocations (same pattern the backgrounded
    bash hook produces when commands are typed quickly) must not
    clobber each other's buffer writes. Runs real subprocesses against
    the actual file-locked code path, not just in-process calls."""
    import subprocess
    watcher_path = Path(watcher.__file__)
    env = dict(**{
        "SENSEI_SHELL_STATE_DIR": str(tmp_path),
        "SENSEI_TELEMETRY_URL": "http://127.0.0.1:1",
        "SENSEI_BASE_URL": "http://127.0.0.1:1",
        "PATH": "/usr/bin:/bin",
    })
    procs = [
        subprocess.Popen(["python3", str(watcher_path), f"cmd{i}", "/home/user"], env=env)
        for i in range(15)
    ]
    for p in procs:
        assert p.wait(timeout=10) == 0

    import json
    buffer = json.loads((tmp_path / "shell_buffer.json").read_text())
    assert len(buffer) == 15  # every invocation's write survived, none lost to the race
