"""
editor_detector.py — Sensei's second real detector: undo storms, named
explicitly in Digital_Sensei.md's Pattern Detection list alongside
"repeated manual sequences" (that's shell_detector.py's job).

Same shape and same philosophy as shell_detector.py on purpose (see that
file's docstring): a pure function over a plain list of dicts, no HTTP,
no state, deterministic on identical input. main.py's
/sensei/detect/editor endpoint is the only thing that wires this to the
real op_nudge pipeline and to dedup state.

What it finds: a run of consecutive "undo" events, uninterrupted by any
other event type, whose count reaches min_undos AND whose whole span
(last event's ts minus first event's ts) is within window_seconds. Both
conditions matter for the same reason the name "storm" implies rate, not
just count: four undos spread across an unhurried afternoon of genuine
editing aren't the same signal as four undos in the same eight seconds.
If `file` is present on events, a storm is scoped to one file — undoing
on file A doesn't get lumped in with unrelated undoing on file B.
"""

DEFAULT_MIN_UNDOS = 4
DEFAULT_WINDOW_SECONDS = 30.0


def find_undo_storms(events, min_undos=DEFAULT_MIN_UNDOS, window_seconds=DEFAULT_WINDOW_SECONDS):
    """events: chronological list of {"type": str, "ts": float, "file": Optional[str]},
    oldest first. Only "undo" events form storms; any other type breaks
    a run in progress. A missing "file" key is treated as one shared
    scope (None), same as any other file value — it only has to be
    consistent within a run, not present at all.

    Returns a list of {"count", "start_ts", "end_ts", "file"} dicts, one
    per qualifying storm, in the order the storms occurred.
    """
    storms = []
    run = []

    def _flush():
        if len(run) >= min_undos:
            span = run[-1]["ts"] - run[0]["ts"]
            if span <= window_seconds:
                storms.append({
                    "count": len(run),
                    "start_ts": run[0]["ts"],
                    "end_ts": run[-1]["ts"],
                    "file": run[0].get("file"),
                })
        run.clear()

    for event in events:
        if event.get("type") != "undo":
            _flush()
            continue
        if run and run[-1].get("file") != event.get("file"):
            _flush()
        run.append(event)
    _flush()

    return storms


def storm_key(storm):
    """Stable dedup key. Deliberately includes start_ts (not just file +
    count) — a NEW storm on the same file later is a new event worth its
    own nudge, not the same one recurring; op_has_suggested_chain's
    'already suggested, never again' semantics only make sense here for
    this exact storm, not 'undoing on this file' as a standing fact."""
    return f"undo_storm:{storm['file']}:{storm['start_ts']}:{storm['count']}"


def format_storm_message(storm):
    file_part = f" on {storm['file']}" if storm.get("file") else ""
    return f"{storm['count']} undos in a row{file_part} — want to talk through the approach?"
