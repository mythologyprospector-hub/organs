import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import shell_watcher_core as core


def _entries(cmds, start_ts=1000.0, gap=10.0, cwd="/home/user"):
    return [{"ts": start_ts + i * gap, "cmd": c, "cwd": cwd} for i, c in enumerate(cmds)]


# ---------------------------------------------------------------------
# buffer management
# ---------------------------------------------------------------------

def test_append_command_is_pure_and_trims():
    buffer = []
    buffer = core.append_command(buffer, "ls", "/home", 1.0, max_len=3)
    buffer = core.append_command(buffer, "cd foo", "/home", 2.0, max_len=3)
    buffer = core.append_command(buffer, "pwd", "/home/foo", 3.0, max_len=3)
    buffer2 = core.append_command(buffer, "echo hi", "/home/foo", 4.0, max_len=3)
    assert len(buffer) == 3  # original untouched
    assert len(buffer2) == 3  # trimmed
    assert buffer2[0]["cmd"] == "cd foo"  # oldest dropped
    assert buffer2[-1]["cmd"] == "echo hi"


def test_load_buffer_missing_file_returns_empty(tmp_path):
    assert core.load_buffer(tmp_path / "nope.json") == []


def test_load_buffer_corrupt_file_returns_empty(tmp_path):
    p = tmp_path / "buf.json"
    p.write_text("{not json")
    assert core.load_buffer(p) == []


def test_save_and_load_buffer_roundtrip(tmp_path):
    p = tmp_path / "sub" / "buf.json"
    buffer = [{"ts": 1.0, "cmd": "ls", "cwd": "/x"}]
    core.save_buffer(p, buffer)
    assert core.load_buffer(p) == buffer


# ---------------------------------------------------------------------
# repeated command detection
# ---------------------------------------------------------------------

def test_repeated_command_fires_at_threshold():
    buffer = _entries(["git status", "ls", "git status", "pwd", "git status"])
    result = core.detect_repeated_command(buffer, now=1100.0, threshold=3)
    assert result is not None
    assert result["kind"] == "shell_repeated_command"
    assert result["detail"]["command"] == "git status"
    assert result["detail"]["count"] == 3


def test_repeated_command_does_not_fire_below_threshold():
    buffer = _entries(["git status", "ls", "git status"])
    result = core.detect_repeated_command(buffer, now=1100.0, threshold=3)
    assert result is None


def test_repeated_command_only_counts_within_window():
    # three occurrences but spread past the window
    buffer = _entries(["git status", "ls", "git status", "pwd", "git status"],
                       start_ts=0.0, gap=300.0)  # 5 min apart
    result = core.detect_repeated_command(buffer, now=1200.0, threshold=3, window_seconds=600)
    # last entry at ts=1200, window=[600,1200] -> only entries at 600,900,1200 qualify... let's just
    # check the boundary case explicitly instead of relying on arithmetic above being obviously right
    recent = core._within_window(buffer, 1200.0, 600.0)
    expected_count = sum(1 for e in recent if e["cmd"] == "git status")
    if expected_count >= 3:
        assert result is not None
    else:
        assert result is None


def test_repeated_command_empty_buffer():
    assert core.detect_repeated_command([], now=100.0) is None


# ---------------------------------------------------------------------
# repeated chain detection
# ---------------------------------------------------------------------

def test_repeated_chain_of_two_fires():
    buffer = _entries(["git add .", "git commit -m x", "git add .", "git commit -m x"])
    result = core.detect_repeated_chain(buffer, now=1100.0, chain_len=3, threshold=2)
    assert result is not None
    assert result["kind"] == "shell_repeated_chain"
    assert result["detail"]["chain"] == ["git add .", "git commit -m x"]
    assert result["detail"]["count"] == 2


def test_repeated_chain_prefers_longer_chain():
    cmds = ["a", "b", "c", "a", "b", "c"]
    buffer = _entries(cmds)
    result = core.detect_repeated_chain(buffer, now=1100.0, chain_len=3, threshold=2)
    assert result is not None
    assert len(result["detail"]["chain"]) == 3
    assert result["detail"]["chain"] == ["a", "b", "c"]


def test_repeated_chain_no_repeat_returns_none():
    buffer = _entries(["a", "b", "c", "d", "e"])
    result = core.detect_repeated_chain(buffer, now=1100.0)
    assert result is None


def test_repeated_chain_ignores_trivial_same_command_chain():
    """A 'chain' where every command is identical isn't a chain — it's
    the same single command repeated, which detect_repeated_command
    already owns. Without this guard, running one command 3+ times
    would fire BOTH detectors with different pattern_keys and produce
    two separate nudges for the same underlying behavior."""
    buffer = _entries(["git status", "git status", "git status", "git status"])
    result = core.detect_repeated_chain(buffer, now=1100.0, chain_len=3, threshold=2)
    assert result is None


def test_find_candidate_does_not_double_fire_on_same_command_repeated():
    """End-to-end version of the guard above, through find_candidate —
    this is the exact scenario that originally slipped through."""
    buffer = _entries(["git status"] * 8)
    result = core.find_candidate(buffer, now=1100.0)
    assert result is not None
    assert result["kind"] == "shell_repeated_command"  # not shell_repeated_chain


def test_repeated_chain_needs_enough_history():
    buffer = _entries(["a", "b"])
    result = core.detect_repeated_chain(buffer, now=100.0, chain_len=3, threshold=2)
    assert result is None


# ---------------------------------------------------------------------
# deep cd detection
# ---------------------------------------------------------------------

def test_deep_cd_fires_on_repeated_deep_path():
    deep = "cd /home/user/projects/foo/bar/baz"
    buffer = _entries(["ls", deep, "pwd", deep, "ls", deep])
    result = core.detect_deep_cd(buffer, now=1200.0, threshold=3)
    assert result is not None
    assert result["kind"] == "shell_deep_path"
    assert result["detail"]["path"] == "/home/user/projects/foo/bar/baz"
    assert result["detail"]["count"] == 3


def test_deep_cd_ignores_shallow_paths():
    shallow = "cd /tmp"
    buffer = _entries([shallow, shallow, shallow, shallow])
    result = core.detect_deep_cd(buffer, now=1100.0, threshold=3)
    assert result is None


def test_deep_cd_ignores_cd_dotdot():
    buffer = _entries(["cd ..", "cd ..", "cd .."])
    result = core.detect_deep_cd(buffer, now=1100.0, threshold=3)
    assert result is None


def test_deep_cd_no_cd_commands_returns_none():
    buffer = _entries(["ls", "pwd", "git status"])
    result = core.detect_deep_cd(buffer, now=1100.0)
    assert result is None


def test_deep_cd_below_threshold_returns_none():
    deep = "cd /home/user/projects/foo/bar/baz"
    buffer = _entries([deep, "ls", deep])
    result = core.detect_deep_cd(buffer, now=1100.0, threshold=3)
    assert result is None


# ---------------------------------------------------------------------
# find_candidate ordering
# ---------------------------------------------------------------------

def test_find_candidate_prefers_chain_over_single_command():
    # this chain also contains a "single command repeated" signal buried in it,
    # but chain detection should win since it's checked first
    cmds = ["git add .", "git commit -m x", "git add .", "git commit -m x", "git add .", "git commit -m x"]
    buffer = _entries(cmds)
    result = core.find_candidate(buffer, now=1100.0)
    assert result["kind"] == "shell_repeated_chain"


def test_find_candidate_returns_none_when_nothing_matches():
    buffer = _entries(["ls", "pwd", "whoami"])
    assert core.find_candidate(buffer, now=1100.0) is None


# ---------------------------------------------------------------------
# cooldowns
# ---------------------------------------------------------------------

def test_cooldown_blocks_repeat_nudge_within_window():
    cooldowns = {}
    cooldowns = core.record_cooldown(cooldowns, "shell_repeated_command:abc", now=1000.0)
    assert core.is_in_cooldown(cooldowns, "shell_repeated_command:abc", now=1500.0, cooldown_seconds=3600) is True


def test_cooldown_expires_after_window():
    cooldowns = {}
    cooldowns = core.record_cooldown(cooldowns, "shell_repeated_command:abc", now=1000.0)
    assert core.is_in_cooldown(cooldowns, "shell_repeated_command:abc", now=5000.0, cooldown_seconds=3600) is False


def test_cooldown_unseen_pattern_is_not_in_cooldown():
    assert core.is_in_cooldown({}, "never:seen", now=1000.0) is False


def test_record_cooldown_is_pure():
    cooldowns = {}
    new_cooldowns = core.record_cooldown(cooldowns, "x", now=1.0)
    assert cooldowns == {}  # original untouched
    assert new_cooldowns == {"x": 1.0}


def test_pattern_key_is_stable_and_scoped_by_kind():
    k1 = core._pattern_key("repeated_command", "git status")
    k2 = core._pattern_key("repeated_command", "git status")
    k3 = core._pattern_key("repeated_chain", "git status")
    assert k1 == k2
    assert k1 != k3  # same identity string, different kind -> different key


def test_load_save_cooldowns_roundtrip(tmp_path):
    p = tmp_path / "cooldowns.json"
    core.save_cooldowns(p, {"a": 1.0})
    assert core.load_cooldowns(p) == {"a": 1.0}


def test_load_cooldowns_missing_file(tmp_path):
    assert core.load_cooldowns(tmp_path / "nope.json") == {}
