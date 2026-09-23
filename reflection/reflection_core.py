"""
reflection_core.py — the muttering-in-the-background organ.

Not a new memory subsystem — GOAL.md's "Reflection" book was deliberately
never given its own storage. This is why: it's a periodic WRITER into
Memory, using Memory's own API like any other organ would, not a special
internal path. What it writes is honest about what it is — low
confidence, self-authored, tagged — not presented as fact.

OFF by default. Every cycle only runs if explicitly enabled, and the
toggle is checked fresh on every tick — flipping it off takes effect on
the very next cycle, not "after a restart."

The three real actions (fetch context, generate a thought, write it
back) are all passed in as functions rather than hardcoded, so the tick
logic itself — state handling, error handling, history — is fully
testable without a real model, real Memory, or a network anywhere near
the test.
"""
import json
import os
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE_PATH = Path(os.environ.get("REFLECTION_STATE_PATH", str(HERE / "state.json"))).expanduser()
HISTORY_PATH = Path(os.environ.get("REFLECTION_HISTORY_PATH", str(HERE / "history.jsonl"))).expanduser()

DEFAULT_STATE = {
    "enabled": False,  # safety first — never mutters until told to
    "interval_seconds": 300,
    "model": "phi4-mini:latest",
    "max_context_entries": 8,
    "max_context_chars": 2000,
}

REFLECTION_PROMPT_TEMPLATE = """You are thinking to yourself in the background, the way a person mutters \
while working through a problem. You are NOT answering anyone, NOT responding to a request, and nobody is \
waiting on this. Just notice what stands out in the recent activity below — a pattern, something odd, an \
unresolved thread, a connection between two things. A sentence or two. If genuinely nothing stands out, \
say so plainly instead of inventing something.

Recent activity:
{context}

Your thought (1-3 plain sentences, no preamble):"""


class ReflectionError(Exception):
    pass


def ensure_files():
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not STATE_PATH.exists():
        STATE_PATH.write_text(json.dumps(DEFAULT_STATE, indent=2))
    if not HISTORY_PATH.exists():
        HISTORY_PATH.touch()


def load_state():
    ensure_files()
    try:
        state = json.loads(STATE_PATH.read_text())
    except json.JSONDecodeError:
        state = dict(DEFAULT_STATE)
        STATE_PATH.write_text(json.dumps(state, indent=2))
    # backfill any keys an older state.json might be missing
    for k, v in DEFAULT_STATE.items():
        state.setdefault(k, v)
    return state


def save_state(state):
    ensure_files()
    STATE_PATH.write_text(json.dumps(state, indent=2))
    return state


def op_get_status():
    state = load_state()
    history = load_history(n=1)
    return {
        **state,
        "last_run_ts": history[0]["ts"] if history else None,
        "last_run_success": history[0]["success"] if history else None,
        "run_count": _history_count(),
    }


def op_enable():
    state = load_state()
    state["enabled"] = True
    return save_state(state)


def op_disable():
    state = load_state()
    state["enabled"] = False
    return save_state(state)


def op_configure(interval_seconds: int = None, model: str = None,
                  max_context_entries: int = None, max_context_chars: int = None):
    state = load_state()
    if interval_seconds is not None:
        if interval_seconds < 10:
            raise ReflectionError("interval_seconds must be at least 10 — this runs unattended, keep it sane")
        state["interval_seconds"] = interval_seconds
    if model is not None:
        state["model"] = model
    if max_context_entries is not None:
        state["max_context_entries"] = max_context_entries
    if max_context_chars is not None:
        state["max_context_chars"] = max_context_chars
    return save_state(state)


def _history_count():
    ensure_files()
    return sum(1 for _ in HISTORY_PATH.open("r", encoding="utf-8")) if HISTORY_PATH.exists() else 0


def load_history(n: int = 20):
    """Newest first. Skips any trailing line that fails to parse as JSON
    — e.g. a process killed mid-write leaving a truncated final line —
    rather than letting one bad line take down every caller of this
    function, including op_get_status(). Mirrors load_state()'s existing
    defense against a corrupted state.json; history.jsonl deserves the
    same treatment since it's written the same unattended, unsupervised
    way."""
    ensure_files()
    if not HISTORY_PATH.exists():
        return []
    lines = HISTORY_PATH.read_text(encoding="utf-8").strip().splitlines()
    selected = lines[-n:] if n > 0 else []
    entries = []
    for line in reversed(selected):
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _record_history(entry):
    with HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def build_prompt(context_text: str) -> str:
    return REFLECTION_PROMPT_TEMPLATE.format(context=context_text)


def op_tick(fetch_context, generate_thought, write_reflection, force: bool = False):
    """One cycle: fetch recent context, generate a thought, write it to
    Memory. `force=True` bypasses the enabled check — used by the manual
    /tick endpoint so you can test without waiting for the loop or
    flipping the toggle on. The background loop itself always calls with
    force=False, respecting the toggle on every single cycle.

    fetch_context()      -> str
    generate_thought(prompt: str) -> str
    write_reflection(text: str)   -> dict (whatever the write returned)

    Never raises for a normal failure (context unreachable, model
    unreachable, write failed) — records it in history and returns a
    result dict with success=False instead. A stuck dependency should
    never crash this organ or the loop that calls it repeatedly.
    """
    state = load_state()
    now = time.time()

    if not force and not state["enabled"]:
        return {"ran": False, "reason": "disabled"}

    try:
        context = fetch_context(state["max_context_entries"], state["max_context_chars"])
    except Exception as e:
        result = {"ran": True, "success": False, "stage": "fetch_context", "error": str(e), "ts": now}
        _record_history(result)
        return result

    if not context.strip():
        result = {"ran": True, "success": True, "skipped": True, "reason": "nothing to reflect on", "ts": now}
        _record_history(result)
        return result

    prompt = build_prompt(context)

    try:
        thought = generate_thought(prompt)
    except Exception as e:
        result = {"ran": True, "success": False, "stage": "generate", "error": str(e), "ts": now}
        _record_history(result)
        return result

    if not thought or not thought.strip():
        result = {"ran": True, "success": True, "skipped": True, "reason": "empty thought", "ts": now}
        _record_history(result)
        return result

    try:
        write_result = write_reflection(thought.strip())
    except Exception as e:
        result = {"ran": True, "success": False, "stage": "write", "error": str(e), "thought": thought.strip(), "ts": now}
        _record_history(result)
        return result

    result = {"ran": True, "success": True, "thought": thought.strip(), "write_result": write_result, "ts": now}
    _record_history(result)
    return result
