"""
main.py — the Digital Sensei organ.

Run it:
    pip install fastapi uvicorn requests --break-system-packages
    uvicorn main:app --host 127.0.0.1 --port 8012

Always running, like every other organ (registry, health, /info never
go away). What toggles is MODE, not the process:

    watching  — default on every boot. Observes, never interrupts.
    ready     — observes AND is allowed to surface nudges.

    curl -X POST localhost:8012/sensei/mode -d '{"mode":"ready"}' \
         -H 'Content-Type: application/json'
    curl -X POST localhost:8012/sensei/mode -d '{"mode":"watching"}' \
         -H 'Content-Type: application/json'
    curl localhost:8012/sensei/status

Switching modes takes effect immediately — the next nudge generated
checks current mode, there's no restart and nothing queued from before
the switch gets released in a batch.

Nudge delivery is a desktop toast (notify-send) when running with a
display; falls back to a log line if notify-send isn't available so
this never crashes a headless test run or a box without a DE.
"""
import json as _json
import logging
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))

from organ_base import create_organ_app, HealthCheck, OrganError, correlation_headers  # noqa: E402
from organ_client import attach_to_registry, discover, RegistryError  # noqa: E402
import sensei_core as sc  # noqa: E402
import shell_detector as sd  # noqa: E402
import editor_detector as ed  # noqa: E402

ORGAN_NAME = "sensei"
ORGAN_VERSION = "0.1.0"
SELF_BASE_URL = os.environ.get("SENSEI_BASE_URL", "http://localhost:8012")

CAPABILITIES = ["status", "mode", "nudge", "history", "respond", "detect_shell", "detect_editor"]

logger = logging.getLogger("organ.sensei")


def _state_check():
    try:
        sc.ensure_files()
        return True, f"state OK at {sc.STATE_PATH}"
    except Exception as e:
        return False, str(e)


app = create_organ_app(
    name=ORGAN_NAME,
    version=ORGAN_VERSION,
    description="Digital Sensei: system-wide human-optimization organ. "
                 "Watches editor/shell/writing/tool activity via Telemetry and "
                 "Introspection, and — only when explicitly in 'ready' mode — "
                 "surfaces small nudges. Defaults to 'watching' (muted) on "
                 "every boot; never interrupts unless asked to.",
    capabilities=CAPABILITIES,
    health_checks=[HealthCheck("state", _state_check)],
)

attach_to_registry(app, name=ORGAN_NAME, base_url=SELF_BASE_URL, version=ORGAN_VERSION, capabilities=CAPABILITIES)


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except sc.SenseiError as e:
        raise OrganError(code="sensei_error", message=str(e), status_code=400)


# ---------------------------------------------------------------------------
# BUS publishing — fire-and-forget, same pattern as memory/main.py
# ---------------------------------------------------------------------------

def _publish_event(topic: str, event_type: str, payload: dict):
    try:
        comm_url = discover("communications")
    except RegistryError:
        return
    try:
        req = urllib.request.Request(
            f"{comm_url}/bus/topics/{topic}/publish",
            data=_json.dumps({"event_type": event_type, "payload": payload, "publisher": "sensei"}).encode("utf-8"),
            headers=correlation_headers({"Content-Type": "application/json"}),
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2.0)
    except (urllib.error.URLError, urllib.error.HTTPError):
        pass


# ---------------------------------------------------------------------------
# nudge delivery — desktop toast, degrades gracefully
# ---------------------------------------------------------------------------

def _deliver_toast(message: str):
    notify_bin = shutil.which("notify-send")
    if notify_bin is None:
        logger.info(f"[sensei nudge, no notify-send available] {message}")
        return
    try:
        subprocess.run(
            [notify_bin, "Digital Sensei", message],
            check=False, timeout=5,
        )
    except Exception as e:
        logger.warning(f"notify-send failed, falling back to log: {e}")
        logger.info(f"[sensei nudge] {message}")


# ---------------------------------------------------------------------------
# Memory write for accepted/rejected nudges — feeds the "Human Update" /
# "Memory Update" steps of the core loop. Fire-and-forget like _publish_event;
# a memory outage shouldn't fail the response endpoint itself.
# ---------------------------------------------------------------------------

def _write_memory(text: str, tags: list, confidence: float = 0.5):
    try:
        memory_url = discover("memory")
    except RegistryError:
        return
    try:
        payload = _json.dumps({
            "text": text, "tags": tags, "provenance": "self",
            "witness": "inferred", "confidence": confidence, "owner": "sensei",
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{memory_url}/memory/add", data=payload,
            headers=correlation_headers({"Content-Type": "application/json"}), method="POST",
        )
        urllib.request.urlopen(req, timeout=5.0)
    except (urllib.error.URLError, urllib.error.HTTPError):
        pass


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------

class ModeRequest(BaseModel):
    mode: str


class NudgeRequest(BaseModel):
    kind: str
    message: str
    source: str


class RespondRequest(BaseModel):
    nudge_ts: float
    accepted: bool


class ShellDetectRequest(BaseModel):
    commands: list[str]


class EditorEvent(BaseModel):
    type: str
    ts: float
    file: Optional[str] = None


class EditorDetectRequest(BaseModel):
    events: list[EditorEvent]


@app.get("/sensei/status")
def status():
    return _wrap(sc.op_get_status)


@app.post("/sensei/mode")
def set_mode(req: ModeRequest):
    result = _wrap(sc.op_set_mode, req.mode)
    _publish_event("sensei.mode", "mode_changed", {"mode": req.mode})
    return result


@app.post("/sensei/nudge")
def nudge(req: NudgeRequest):
    """Called by detection logic (editor/shell/writing watchers — future
    work) when a candidate nudge is found. Mode is checked HERE, at
    generation time, not at some later delivery step — see sensei_core
    docstring for why that ordering is the whole point."""
    result = _wrap(sc.op_nudge, req.kind, req.message, req.source, deliver_fn=_deliver_toast)
    event_type = "nudge_offered" if result["delivered"] else "nudge_suppressed"
    _publish_event("sensei.nudges", event_type, {
        "kind": req.kind, "message": req.message, "source": req.source,
    })
    return result


@app.post("/sensei/respond")
def respond(req: RespondRequest):
    """Records acceptance/rejection of a delivered nudge — the Human
    Update step. Writes a low-confidence memory entry so future
    sessions can see accepted vs. rejected patterns, same honesty
    convention reflection uses (tagged, not presented as settled fact)."""
    result = _wrap(sc.op_record_response, req.nudge_ts, req.accepted)
    event_type = "nudge_accepted" if req.accepted else "nudge_rejected"
    _publish_event("sensei.nudges", event_type, {"nudge_ts": req.nudge_ts})
    _write_memory(
        f"Sensei nudge at {req.nudge_ts} was {'accepted' if req.accepted else 'rejected'}.",
        tags=["sensei", "nudge_response"],
        confidence=0.6,
    )
    return result


@app.get("/sensei/history")
def history(n: int = 20, delivered_only: bool = False):
    return sc.load_history(n, delivered_only=delivered_only)


@app.post("/sensei/detect/shell")
def detect_shell(req: ShellDetectRequest):
    """The first real Observe -> Detect wiring, called by a real shell
    watcher (see shell_watcher.sh) with a batch of recent shell history —
    chronological, oldest first, already stripped of history line numbers.

    Detection itself (shell_detector.find_repeated_chains) is pure and
    stateless; this endpoint is what makes it stateful and real: every
    candidate chain routes through the SAME op_nudge gate every other
    nudge source uses (mode still decided at generation time, nothing
    here bypasses that), and a chain already suggested before is skipped
    rather than re-nudging the same pattern on every scan.
    """
    candidates = sd.find_repeated_chains(req.commands)
    new_nudges = []
    for candidate in candidates:
        key = sd.chain_key(candidate["chain"])
        if sc.op_has_suggested_chain(key):
            continue
        message = sd.format_chain_message(candidate)
        result = _wrap(sc.op_nudge, "shell", message, "shell_watcher", deliver_fn=_deliver_toast)
        sc.op_mark_chain_suggested(key, message)
        event_type = "nudge_offered" if result["delivered"] else "nudge_suppressed"
        _publish_event("sensei.nudges", event_type, {
            "kind": "shell", "message": message, "source": "shell_watcher",
        })
        new_nudges.append(result)
    return {"candidates_found": len(candidates), "new_nudges": new_nudges}


@app.post("/sensei/detect/editor")
def detect_editor(req: EditorDetectRequest):
    """Same shape as /sensei/detect/shell, second detector: undo storms.
    Called with a batch of recent editor events — chronological, oldest
    first. Detection (editor_detector.find_undo_storms) is pure and
    stateless; this endpoint makes it real the same way: routes each new
    storm through the same op_nudge gate, skips a storm already
    suggested before (keyed by file+start_ts+count, so a genuinely new
    storm later still nudges, but re-scanning the same window doesn't
    re-nudge about the same one)."""
    events = [e.model_dump() for e in req.events]
    storms = ed.find_undo_storms(events)
    new_nudges = []
    for storm in storms:
        key = ed.storm_key(storm)
        if sc.op_has_suggested_chain(key):
            continue
        message = ed.format_storm_message(storm)
        result = _wrap(sc.op_nudge, "editor", message, "editor_watcher", deliver_fn=_deliver_toast)
        sc.op_mark_chain_suggested(key, message)
        event_type = "nudge_offered" if result["delivered"] else "nudge_suppressed"
        _publish_event("sensei.nudges", event_type, {
            "kind": "editor", "message": message, "source": "editor_watcher",
        })
        new_nudges.append(result)
    return {"storms_found": len(storms), "new_nudges": new_nudges}
