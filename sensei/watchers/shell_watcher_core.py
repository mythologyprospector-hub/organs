"""
shell_watcher_core.py — pattern detection for Sensei's shell watcher.

Kept separate from shell_watcher.py (the CLI entry point invoked by the
bash hook) for the same reason sensei_core.py is separate from main.py:
this file is pure — buffer in, candidate pattern out — so it's testable
without touching disk, the network, or a real shell. shell_watcher.py
wires this to real files and real HTTP calls.

What it detects, matching the three shell examples in Digital_Sensei.md:
  - repeated chain -> alias/script suggestion
  - deep path -> bookmark suggestion
and one Sensei didn't list explicitly but the doc's spirit covers:
  - the exact same single command run over and over -> alias suggestion

Every detector requires REPETITION within a rolling time window, not a
single occurrence — a single deep `cd` or a single long command is not
a pattern, it's just something that happened once. Pattern == it kept
happening.

Cooldowns exist so the same detected pattern doesn't nudge again every
time it recurs within the cooldown window — the mode gate in
sensei_core.py already stops nudges from queuing up while muted, but
without a cooldown here a person in "ready" mode running the same
three-command chain ten times in twenty minutes would get ten nudges
for the same thing, which is its own kind of annoying.
"""
import hashlib
import json
import time
from pathlib import Path

DEFAULT_BUFFER_SIZE = 50
DEFAULT_REPEAT_THRESHOLD = 3
DEFAULT_CHAIN_THRESHOLD = 2
DEFAULT_CHAIN_LEN = 3
DEFAULT_WINDOW_SECONDS = 600  # 10 minutes
DEFAULT_COOLDOWN_SECONDS = 3600  # 1 hour
DEEP_CD_MIN_SEGMENTS = 4


def load_buffer(path: Path):
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return []


def save_buffer(path: Path, buffer: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(buffer))


def append_command(buffer: list, cmd: str, cwd: str, ts: float, max_len: int = DEFAULT_BUFFER_SIZE):
    """Returns a NEW buffer list (doesn't mutate in place) with the
    command appended and trimmed to max_len — same reasoning as
    sensei_core's functions being pure, easy to unit test."""
    new_buffer = buffer + [{"ts": ts, "cmd": cmd, "cwd": cwd}]
    if len(new_buffer) > max_len:
        new_buffer = new_buffer[-max_len:]
    return new_buffer


def _within_window(entries: list, now: float, window_seconds: float):
    return [e for e in entries if now - e["ts"] <= window_seconds]


def _pattern_key(kind: str, identity: str):
    """Stable, short key for cooldown tracking — hashed so a very long
    command or chain doesn't produce an unwieldy dict key."""
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"{kind}:{digest}"


def detect_repeated_command(buffer: list, now: float,
                             threshold: int = DEFAULT_REPEAT_THRESHOLD,
                             window_seconds: float = DEFAULT_WINDOW_SECONDS):
    """Same exact command string run >= threshold times within the
    window. Returns a candidate dict or None."""
    recent = _within_window(buffer, now, window_seconds)
    if not recent:
        return None
    last_cmd = recent[-1]["cmd"]
    count = sum(1 for e in recent if e["cmd"] == last_cmd)
    if count >= threshold:
        return {
            "kind": "shell_repeated_command",
            "pattern_key": _pattern_key("repeated_command", last_cmd),
            "message": f"You've run `{last_cmd}` {count} times recently — want an alias for it?",
            "detail": {"command": last_cmd, "count": count},
        }
    return None


def detect_repeated_chain(buffer: list, now: float,
                           chain_len: int = DEFAULT_CHAIN_LEN,
                           threshold: int = DEFAULT_CHAIN_THRESHOLD,
                           window_seconds: float = DEFAULT_WINDOW_SECONDS):
    """Looks for the same N-command sequence (in order, back to back)
    appearing >= threshold times within the window — an n-gram repeat.
    Returns the LONGEST chain length that qualifies (checked from
    chain_len down to 2), so a 3-command repeated chain is reported
    instead of also separately reporting the 2-command sub-chain."""
    recent = _within_window(buffer, now, window_seconds)
    for length in range(chain_len, 1, -1):
        if len(recent) < length * threshold:
            continue
        cmds = [e["cmd"] for e in recent]
        chains = [tuple(cmds[i:i + length]) for i in range(len(cmds) - length + 1)]
        last_chain = chains[-1] if chains else None
        if last_chain is None:
            continue
        count = chains.count(last_chain)
        if count >= threshold:
            if len(set(last_chain)) == 1:
                # every command in this "chain" is identical — that's not
                # a sequence, it's the same single command repeated, which
                # detect_repeated_command already covers under its own
                # pattern_key. Firing here too would double-nudge the same
                # underlying behavior with two different cooldown keys.
                continue
            chain_str = " && ".join(last_chain)
            return {
                "kind": "shell_repeated_chain",
                "pattern_key": _pattern_key("repeated_chain", chain_str),
                "message": f"That {length}-command sequence (`{chain_str}`) has come up {count} times — want a script for it?",
                "detail": {"chain": list(last_chain), "count": count},
            }
    return None


def detect_deep_cd(buffer: list, now: float,
                    threshold: int = DEFAULT_REPEAT_THRESHOLD,
                    window_seconds: float = DEFAULT_WINDOW_SECONDS,
                    min_segments: int = DEEP_CD_MIN_SEGMENTS):
    """Same deep cd target visited >= threshold times within the
    window. Only fires for `cd` commands with a path at least
    min_segments deep, so `cd ..` or `cd /tmp` never qualifies."""
    recent = _within_window(buffer, now, window_seconds)
    cd_targets = [e["cmd"] for e in recent if e["cmd"].startswith("cd ")]
    if not cd_targets:
        return None
    last_target = cd_targets[-1]
    path = last_target[3:].strip()
    segments = [s for s in path.split("/") if s]
    if len(segments) < min_segments:
        return None
    count = cd_targets.count(last_target)
    if count >= threshold:
        return {
            "kind": "shell_deep_path",
            "pattern_key": _pattern_key("deep_cd", path),
            "message": f"You've `cd`'d into `{path}` {count} times — want a bookmark/alias for it?",
            "detail": {"path": path, "count": count},
        }
    return None


DETECTORS = (detect_repeated_command, detect_repeated_chain, detect_deep_cd)


def find_candidate(buffer: list, now: float):
    """Runs detectors in order, returns the first hit. Order matters:
    a repeated chain is a more specific/useful signal than the deep-cd
    inside it would be alone, so chain detection is checked first."""
    for detector in (detect_repeated_chain, detect_repeated_command, detect_deep_cd):
        result = detector(buffer, now)
        if result is not None:
            return result
    return None


def load_cooldowns(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def save_cooldowns(path: Path, cooldowns: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cooldowns))


def is_in_cooldown(cooldowns: dict, pattern_key: str, now: float,
                    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS):
    last = cooldowns.get(pattern_key)
    if last is None:
        return False
    return (now - last) < cooldown_seconds


def record_cooldown(cooldowns: dict, pattern_key: str, now: float):
    """Returns a NEW dict, same pure-function convention as the rest
    of this module."""
    new_cooldowns = dict(cooldowns)
    new_cooldowns[pattern_key] = now
    return new_cooldowns
