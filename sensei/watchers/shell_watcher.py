#!/usr/bin/env python3
"""
shell_watcher.py — invoked once per shell command by shell_hook.bash.

    python3 shell_watcher.py "<command>" "<cwd>"

Fast path is the point: this runs synchronously-ish from PROMPT_COMMAND
(backgrounded with `&` by the hook, but still — no reason to be slow).
Everything here is local file I/O except the two network calls, which
only happen when a NEW pattern is actually found (not on every
invocation) and are given short timeouts so a slow/down organ never
hangs a shell prompt.

What it does, per invocation:
  1. Skip cleanly if the command is empty or is itself an invocation
     of this script (avoids the hook recursively watching itself).
  2. Append the command to Telemetry as a raw, faithful record —
     regardless of whether any pattern fires. Telemetry's job is to
     record operational reality, not to judge it (see telemetry_core.py's
     own docstring) — pattern judgment happens here, not there.
  3. Update the local rolling buffer, run detectors.
  4. If a NEW (not-in-cooldown) pattern is found, POST it to Sensei's
     /sensei/nudge. Sensei itself decides whether to actually surface
     it — that's the mode gate in sensei_core.py, not this file's job.
     This file only decides WHAT counts as a candidate pattern, not
     whether the person gets interrupted.
"""
import fcntl
import json
import os
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shell_watcher_core as core  # noqa: E402

STATE_DIR = Path(os.environ.get("SENSEI_SHELL_STATE_DIR", str(Path.home() / ".local/share/organs/sensei"))).expanduser()
BUFFER_PATH = STATE_DIR / "shell_buffer.json"
COOLDOWN_PATH = STATE_DIR / "shell_cooldowns.json"
LOCK_PATH = STATE_DIR / ".shell_watcher.lock"

TELEMETRY_URL = os.environ.get("SENSEI_TELEMETRY_URL", "http://localhost:8011")
SENSEI_URL = os.environ.get("SENSEI_BASE_URL", "http://localhost:8012")

NETWORK_TIMEOUT = float(os.environ.get("SENSEI_SHELL_WATCHER_TIMEOUT", "1.5"))


@contextmanager
def _state_lock():
    """Serializes the buffer+cooldown read-modify-write cycle across
    concurrent invocations of this script. The bash hook backgrounds
    each invocation independently (`( python3 shell_watcher.py ... & )`)
    so it never blocks the shell prompt — but that means typing several
    commands in quick succession can spawn overlapping processes, and
    without this lock, two of them can each read the buffer BEFORE the
    other's write lands, then both write back, and the second write
    silently clobbers the first — the buffer never actually accumulates
    past whichever invocation writes last.

    fcntl.flock is tied to the open file descriptor, not a pid, so
    there's no stale-lock cleanup to worry about if a process dies
    mid-write — the OS releases it automatically when the fd closes.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOCK_PATH, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _post(url: str, payload: dict, timeout: float = NETWORK_TIMEOUT):
    """Fire-and-forget, same convention as every organ's _publish_event
    — a down or slow organ must never take the shell prompt down with
    it. Returns True/False for testability; callers don't act on it.

    Catches OSError broadly (not just URLError/HTTPError/TimeoutError)
    — connection-refused, DNS failure, and similar low-level socket
    errors don't always surface as the narrower urllib exception types,
    and this call happens BEFORE pattern detection in process_command.
    A narrow except here means Telemetry simply being offline could
    kill the whole invocation before the buffer is ever touched — this
    is exactly the kind of silent failure the backgrounded hook's
    `>/dev/null 2>&1` would hide completely."""
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return False


def emit_telemetry(cmd: str, cwd: str, post_fn=_post):
    return post_fn(f"{TELEMETRY_URL}/telemetry/events", {
        "event_type": "command_executed",
        "source": "sensei_shell_watcher",
        "payload": {"command": cmd, "cwd": cwd},
        "severity": "info",
    })


def send_nudge(candidate: dict, post_fn=_post):
    return post_fn(f"{SENSEI_URL}/sensei/nudge", {
        "kind": candidate["kind"],
        "message": candidate["message"],
        "source": "shell_watcher",
    })


def process_command(cmd: str, cwd: str, now: float = None,
                     emit_fn=emit_telemetry, nudge_fn=send_nudge):
    """The testable core of a single invocation — takes the command
    and cwd, does everything else via injected functions so tests never
    touch the real filesystem or network. Returns a small report dict
    describing what happened, mainly so tests can assert on it."""
    now = now if now is not None else time.time()
    cmd = cmd.strip()
    if not cmd:
        return {"skipped": "empty_command"}
    if "shell_watcher.py" in cmd:
        return {"skipped": "self_invocation"}

    # emit_fn is fire-and-forget BY DESIGN — Telemetry being down, slow,
    # or unreachable must never prevent pattern detection from running.
    # _post() catches the network exceptions we know about, but this
    # try/except is the actual guarantee: whatever emit_fn does, a
    # failure in it can't take the rest of this function down with it.
    try:
        emit_fn(cmd, cwd)
    except Exception:
        pass

    with _state_lock():
        buffer = core.load_buffer(BUFFER_PATH)
        buffer = core.append_command(buffer, cmd, cwd, now)
        core.save_buffer(BUFFER_PATH, buffer)

        candidate = core.find_candidate(buffer, now)
        if candidate is None:
            return {"nudged": False, "reason": "no_pattern"}

        cooldowns = core.load_cooldowns(COOLDOWN_PATH)
        if core.is_in_cooldown(cooldowns, candidate["pattern_key"], now):
            return {"nudged": False, "reason": "cooldown", "pattern_key": candidate["pattern_key"]}

        cooldowns = core.record_cooldown(cooldowns, candidate["pattern_key"], now)
        core.save_cooldowns(COOLDOWN_PATH, cooldowns)

    # nudge_fn (the actual network call) happens OUTSIDE the lock —
    # it's the slow part, and nothing about it needs the buffer/cooldown
    # files held. Holding the lock only across the fast local file I/O
    # keeps concurrent invocations from queuing up behind a network call.
    nudge_fn(candidate)
    return {"nudged": True, "kind": candidate["kind"], "pattern_key": candidate["pattern_key"]}


def main():
    if len(sys.argv) != 3:
        # Silent exit, not an error — a malformed hook invocation
        # should never print noise into someone's shell.
        sys.exit(0)
    cmd, cwd = sys.argv[1], sys.argv[2]
    process_command(cmd, cwd)


if __name__ == "__main__":
    main()
