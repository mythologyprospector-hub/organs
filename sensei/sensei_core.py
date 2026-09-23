"""
sensei_core.py — Digital Sensei's state and nudge pipeline.

The one rule this file exists to enforce: **mode decides whether a nudge
is generated, not just whether it's shown.** Observation always runs
(that part is "fine" per the person who's building this — always
watching is fine). What must never happen is a backlog of suppressed
nudges dumping on the person the instant they unmute. So `op_nudge()`
checks mode BEFORE doing anything with the candidate nudge: in "ready"
mode it's recorded and handed back for delivery; in "watching" mode
(the default, muted) it's recorded as suppressed and nothing is ever
queued to fire later. Detection can still run in the background in
either mode — that's a caller-side concern, not this file's — but this
file is the one place that decides delivery, and it decides it exactly
once, at generation time.

Two modes only, matching what was actually asked for:
  "watching" — observing, never interrupting. Default on every boot.
  "ready"    — observing AND allowed to surface nudges.

No third "off" mode — the organ is a normal always-on service like
every other organ (registry, health, /info). "Leave me alone" is a
state of the service, not the service being stopped.
"""
import json
import os
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE_PATH = Path(os.environ.get("SENSEI_STATE_PATH", str(HERE / "state.json"))).expanduser()
HISTORY_PATH = Path(os.environ.get("SENSEI_HISTORY_PATH", str(HERE / "nudge_history.jsonl"))).expanduser()
SEEN_CHAINS_PATH = Path(os.environ.get("SENSEI_SEEN_CHAINS_PATH", str(HERE / "seen_chains.json"))).expanduser()

VALID_MODES = ("watching", "ready")

DEFAULT_STATE = {
    "mode": "watching",  # muted by default — opt IN to being coached, never opt out
    "mode_changed_ts": None,
}


class SenseiError(Exception):
    pass


def ensure_files():
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not STATE_PATH.exists():
        STATE_PATH.write_text(json.dumps(DEFAULT_STATE, indent=2))
    if not HISTORY_PATH.exists():
        HISTORY_PATH.touch()
    if not SEEN_CHAINS_PATH.exists():
        SEEN_CHAINS_PATH.write_text(json.dumps({}))


def load_state():
    ensure_files()
    try:
        state = json.loads(STATE_PATH.read_text())
    except json.JSONDecodeError:
        state = dict(DEFAULT_STATE)
        STATE_PATH.write_text(json.dumps(state, indent=2))
    for k, v in DEFAULT_STATE.items():
        state.setdefault(k, v)
    return state


def save_state(state):
    ensure_files()
    STATE_PATH.write_text(json.dumps(state, indent=2))
    return state


# ---------------------------------------------------------------------------
# Detector dedup — "have we already suggested this exact pattern before?"
#
# Detectors (shell_detector.py and future editor/writing ones) re-scan a
# rolling window of history on every call, so the same repeated chain would
# otherwise get re-flagged every single time it's still present in that
# window. That's not "still watching" behavior, it's noise — Digital_Sensei.md
# never asked for the same nudge twice. This is intentionally forever, not
# time-boxed: once a chain has been surfaced, re-surfacing it later doesn't
# teach anything new. op_forget_chain exists for the CLI/tests to reverse
# that deliberately (e.g. the person re-adopted an old chain after a long
# gap and would welcome the reminder again).
# ---------------------------------------------------------------------------

def _load_seen_chains():
    ensure_files()
    try:
        return json.loads(SEEN_CHAINS_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def _save_seen_chains(seen):
    ensure_files()
    SEEN_CHAINS_PATH.write_text(json.dumps(seen, indent=2))


def op_has_suggested_chain(key: str) -> bool:
    return key in _load_seen_chains()


def op_mark_chain_suggested(key: str, message: str):
    seen = _load_seen_chains()
    seen[key] = {"message": message, "ts": time.time()}
    _save_seen_chains(seen)
    return seen[key]


def op_forget_chain(key: str) -> bool:
    """Returns True if the key existed and was removed, False if it wasn't
    tracked in the first place — lets a caller distinguish 'cleared' from
    'nothing to clear' instead of both looking like silent success."""
    seen = _load_seen_chains()
    if key not in seen:
        return False
    del seen[key]
    _save_seen_chains(seen)
    return True


def op_get_status():
    state = load_state()
    recent = load_history(n=1)
    return {
        **state,
        "last_nudge_ts": recent[0]["ts"] if recent else None,
        "nudge_count": _history_count(),
    }


def op_set_mode(mode: str):
    if mode not in VALID_MODES:
        raise SenseiError(f"mode must be one of {VALID_MODES}, got {mode!r}")
    state = load_state()
    if state["mode"] == mode:
        return state  # no-op, still returns current state cleanly
    state["mode"] = mode
    state["mode_changed_ts"] = time.time()
    return save_state(state)


def _history_count():
    ensure_files()
    return sum(1 for _ in HISTORY_PATH.open("r", encoding="utf-8")) if HISTORY_PATH.exists() else 0


def load_history(n: int = 20, delivered_only: bool = False):
    """Newest first. Skips any trailing line that fails to parse as
    JSON (e.g. truncated by a killed process mid-write) rather than
    letting one bad line take the whole read down."""
    ensure_files()
    if not HISTORY_PATH.exists():
        return []
    lines = HISTORY_PATH.read_text(encoding="utf-8").strip().splitlines()
    entries = []
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if delivered_only and not entry.get("delivered"):
            continue
        entries.append(entry)
        if len(entries) >= n:
            break
    return entries


def _record_history(entry):
    with HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def op_nudge(kind: str, message: str, source: str, deliver_fn=None):
    """A candidate nudge arrives here from whatever detected it
    (editor watcher, shell watcher, writing watcher — future work).
    This function is the single gate that decides whether it's ever
    shown to the person, based on mode *at generation time*:

      - "ready":    delivered now via deliver_fn (e.g. a toast), and
                     recorded delivered=True.
      - "watching": never delivered, never queued — recorded
                     delivered=False, suppressed=True. It does not
                     wait around to fire later when mode flips.

    deliver_fn(message: str) -> None is injected so this stays testable
    without a real notification backend, same pattern as reflection_core's
    injected fetch/generate/write functions.
    """
    if not message or not message.strip():
        raise SenseiError("nudge message must not be empty")

    state = load_state()
    now = time.time()
    entry = {
        "ts": now,
        "kind": kind,
        "message": message.strip(),
        "source": source,
        "mode_at_generation": state["mode"],
    }

    if state["mode"] == "ready":
        if deliver_fn is not None:
            deliver_fn(message.strip())
        entry["delivered"] = True
    else:
        entry["delivered"] = False
        entry["suppressed"] = True

    _record_history(entry)
    return entry


def op_record_response(nudge_ts: float, accepted: bool):
    """Records whether a delivered nudge was accepted or rejected —
    feeds Memory Update in the core loop. Does not itself write to
    Memory; main.py's endpoint does that over HTTP, same separation
    reflection_core keeps between local state and the real Memory organ."""
    return {"nudge_ts": nudge_ts, "accepted": accepted, "ts": time.time()}
