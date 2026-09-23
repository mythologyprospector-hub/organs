"""
main.py — the Telemetry organ: records what actually happened across
the organism, queryable by source, event type, status, correlation ID,
and time range. See telemetry_core.py's module docstring for the full
design rationale — why this isn't Memory, the wall-clock/monotonic
distinction, and what correlation_id is for.

Run it:
    pip install fastapi uvicorn --break-system-packages
    uvicorn main:app --host 127.0.0.1 --port 8011
"""
import os
import sys
from pathlib import Path
from typing import Optional

from fastapi import Query
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))

from organ_base import create_organ_app, HealthCheck, OrganError  # noqa: E402
from organ_client import attach_to_registry  # noqa: E402
import telemetry_core as tc  # noqa: E402

ORGAN_NAME = "telemetry"
ORGAN_VERSION = "0.1.0"
SELF_BASE_URL = os.environ.get("TELEMETRY_BASE_URL", "http://localhost:8011")

CAPABILITIES = ["emit", "query", "get_event", "timeline", "stats", "backfill"]


def _db_check():
    try:
        tc.op_stats()
        return True, f"{tc.DB_PATH} reachable"
    except Exception as e:
        return False, str(e)


app = create_organ_app(
    name=ORGAN_NAME,
    version=ORGAN_VERSION,
    description="Telemetry organ: the observation layer. Records what happened, "
                 "when, how long it took, and whether it succeeded — permanent "
                 "append-only ledger plus a queryable index. Not Memory: this "
                 "records operational reality without judgment, Memory decides "
                 "what's worth remembering.",
    capabilities=CAPABILITIES,
    health_checks=[HealthCheck("storage", _db_check)],
    # /telemetry/events is hit on EVERY request across EVERY organ (each
    # one's own middleware emits one here on completion) — gating it
    # would mean every single operation anywhere in the system makes an
    # extra blocking Critic call just to record that it happened, and
    # if Critic's own organ also has this middleware, its own act of
    # emitting telemetry about handling a request would try to ask
    # itself whether emitting telemetry is safe: direct infinite
    # recursion. /telemetry/backfill is NOT exempted — that's a real
    # action, gated caution per Critic's own rule table.
    risk_gate_exempt_paths={"/telemetry/events"},
)

attach_to_registry(app, name=ORGAN_NAME, base_url=SELF_BASE_URL, version=ORGAN_VERSION, capabilities=CAPABILITIES)


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except tc.TelemetryError as e:
        raise OrganError(code="telemetry_error", message=str(e), status_code=400)


class EmitRequest(BaseModel):
    event_type: str
    source: str
    actor: Optional[str] = None
    correlation_id: Optional[str] = None
    parent_event_id: Optional[str] = None
    severity: str = "info"
    payload: Optional[dict] = None
    result: Optional[dict] = None
    duration_ms: Optional[float] = None
    status: str = "completed"
    provenance: Optional[dict] = None


@app.post("/telemetry/events")
def emit(req: EmitRequest):
    return _wrap(
        tc.op_emit, req.event_type, req.source, actor=req.actor, correlation_id=req.correlation_id,
        parent_event_id=req.parent_event_id, severity=req.severity, payload=req.payload,
        result=req.result, duration_ms=req.duration_ms, status=req.status, provenance=req.provenance,
    )


@app.get("/telemetry/events")
def query(
    source: Optional[str] = None, event_type: Optional[str] = None, status: Optional[str] = None,
    correlation_id: Optional[str] = None, start: Optional[float] = None, end: Optional[float] = None,
    limit: Optional[int] = Query(default=None),
):
    return _wrap(tc.op_query, source, event_type, status, correlation_id, start, end, limit)


@app.get("/telemetry/events/{event_id}")
def get_event(event_id: str):
    return _wrap(tc.op_get_event, event_id)


@app.get("/telemetry/recent")
def recent(limit: int = 50):
    return _wrap(tc.op_query, None, None, None, None, None, None, limit)


@app.get("/telemetry/timeline")
def timeline(correlation_id: str):
    return _wrap(tc.op_timeline, correlation_id)


@app.get("/telemetry/stats")
def stats():
    return _wrap(tc.op_stats)


@app.post("/telemetry/backfill")
def backfill():
    return _wrap(tc.op_backfill)
