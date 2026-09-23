"""
telemetry_core.py — the observation layer. Records what actually
happened across the organism: what ran, when, how long it took, whether
it succeeded, what changed. This is NOT Memory. Memory decides what
operational reality is worth remembering long-term; Telemetry just
records operational reality, faithfully, without judgment — a sandbox
job starting and exiting 0 is a telemetry event whether or not anyone
ever decides it's worth a fact or a scar.

Storage mirrors Memory's own established pattern exactly, on purpose:
  - telemetry.jsonl   permanent, append-only, the raw record. Never
                       rewritten, same as Memory's ledger.jsonl.
  - telemetry.sqlite3  queryable index over the same events, rebuilt
                       from nothing but useful for the filtered queries
                       (source, event_type, status, correlation_id, time
                       range) a TUI or a model actually needs to ask.

Two kinds of time on every event, and this is deliberate, not
decoration: `timestamp` (wall-clock, "when did this happen") and
`monotonic_time` (`time.monotonic()`, immune to clock adjustments,
NTP corrections, and DST — "how much time elapsed between two events on
THIS process's clock"). Duration math anywhere downstream should use
monotonic deltas, never wall-clock subtraction — a caller supplies
`duration_ms` directly when it knows it (it measured its own operation),
Telemetry never tries to reconstruct a duration from two wall-clock
timestamps itself.

A `correlation_id` threads events from one externally-initiated
operation into a single reconstructable causal chain — e.g. an I/O
Interface request, the Executive goal it becomes, the Critic evaluation
that gates it, the Orchestrator action it triggers. op_timeline() pulls
exactly that chain back out, chronologically.
"""
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("TELEMETRY_DATA_DIR", str(HERE / "data"))).expanduser()
LEDGER_PATH = DATA_DIR / "telemetry.jsonl"
DB_PATH = DATA_DIR / "telemetry.sqlite3"

VALID_STATUSES = {"started", "completed", "failed", "cancelled"}
VALID_SEVERITIES = {"debug", "info", "warning", "error", "critical"}
DEFAULT_QUERY_LIMIT = 100
MAX_QUERY_LIMIT = 1000


class TelemetryError(Exception):
    pass


def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not LEDGER_PATH.exists():
        LEDGER_PATH.touch()


def get_db():
    ensure_data_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            timestamp REAL NOT NULL,
            monotonic_time REAL NOT NULL,
            event_type TEXT NOT NULL,
            source TEXT NOT NULL,
            actor TEXT,
            correlation_id TEXT,
            parent_event_id TEXT,
            severity TEXT NOT NULL,
            payload TEXT NOT NULL,
            result TEXT,
            duration_ms REAL,
            status TEXT NOT NULL,
            provenance TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_source ON events(source)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_event_type ON events(event_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_status ON events(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_correlation_id ON events(correlation_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)")
    conn.commit()
    return conn


def _row_to_event(row) -> dict:
    (event_id, timestamp, monotonic_time, event_type, source, actor, correlation_id,
     parent_event_id, severity, payload, result, duration_ms, status, provenance) = row
    return {
        "event_id": event_id, "timestamp": timestamp, "monotonic_time": monotonic_time,
        "event_type": event_type, "source": source, "actor": actor,
        "correlation_id": correlation_id, "parent_event_id": parent_event_id,
        "severity": severity, "payload": json.loads(payload),
        "result": json.loads(result) if result is not None else None,
        "duration_ms": duration_ms, "status": status,
        "provenance": json.loads(provenance) if provenance is not None else None,
    }


def op_emit(event_type: str, source: str, actor: str = None, correlation_id: str = None,
            parent_event_id: str = None, severity: str = "info", payload: dict = None,
            result: dict = None, duration_ms: float = None, status: str = "completed",
            provenance: dict = None):
    """Records one event. event_id/timestamp/monotonic_time are always
    assigned here, server-side — never trusted from a caller, so two
    organs can never collide on an event_id and the wall-clock/monotonic
    pairing is always internally consistent."""
    if not event_type or not event_type.strip():
        raise TelemetryError("event_type must not be empty")
    if not source or not source.strip():
        raise TelemetryError("source must not be empty")
    if status not in VALID_STATUSES:
        raise TelemetryError(f"status must be one of {sorted(VALID_STATUSES)}, got {status!r}")
    if severity not in VALID_SEVERITIES:
        raise TelemetryError(f"severity must be one of {sorted(VALID_SEVERITIES)}, got {severity!r}")

    event = {
        "event_id": uuid.uuid4().hex, "timestamp": time.time(), "monotonic_time": time.monotonic(),
        "event_type": event_type, "source": source, "actor": actor,
        "correlation_id": correlation_id, "parent_event_id": parent_event_id,
        "severity": severity, "payload": payload or {}, "result": result,
        "duration_ms": duration_ms, "status": status, "provenance": provenance,
    }

    ensure_data_dir()
    with open(LEDGER_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")

    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO events (event_id, timestamp, monotonic_time, event_type, source,
                                    actor, correlation_id, parent_event_id, severity, payload,
                                    result, duration_ms, status, provenance)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (event["event_id"], event["timestamp"], event["monotonic_time"], event["event_type"],
             event["source"], event["actor"], event["correlation_id"], event["parent_event_id"],
             event["severity"], json.dumps(event["payload"]),
             json.dumps(event["result"]) if event["result"] is not None else None,
             event["duration_ms"], event["status"],
             json.dumps(event["provenance"]) if event["provenance"] is not None else None),
        )
        conn.commit()
    finally:
        conn.close()

    return event


def op_query(source: str = None, event_type: str = None, status: str = None,
             correlation_id: str = None, start: float = None, end: float = None,
             limit: int = None, ascending: bool = False):
    limit = DEFAULT_QUERY_LIMIT if limit is None else min(limit, MAX_QUERY_LIMIT)
    if limit < 1:
        raise TelemetryError("limit must be at least 1")
    clauses, params = [], []
    if source is not None:
        clauses.append("source = ?"); params.append(source)
    if event_type is not None:
        clauses.append("event_type = ?"); params.append(event_type)
    if status is not None:
        clauses.append("status = ?"); params.append(status)
    if correlation_id is not None:
        clauses.append("correlation_id = ?"); params.append(correlation_id)
    if start is not None:
        clauses.append("timestamp >= ?"); params.append(start)
    if end is not None:
        clauses.append("timestamp <= ?"); params.append(end)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    order = "ASC" if ascending else "DESC"
    sql = f"SELECT * FROM events {where} ORDER BY timestamp {order} LIMIT ?"
    params.append(limit)

    conn = get_db()
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [_row_to_event(r) for r in rows]


def op_get_event(event_id: str):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise TelemetryError(f"event {event_id!r} not found")
    return _row_to_event(row)


def op_timeline(correlation_id: str):
    """Chronological reconstruction of one causal chain — everything
    sharing a correlation_id, oldest first. This is the concrete answer
    to 'what actually happened for request ABC123, in order.'"""
    if not correlation_id or not correlation_id.strip():
        raise TelemetryError("correlation_id must not be empty")
    return op_query(correlation_id=correlation_id, limit=MAX_QUERY_LIMIT, ascending=True)


def op_stats():
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        by_source = dict(conn.execute("SELECT source, COUNT(*) FROM events GROUP BY source").fetchall())
        by_event_type = dict(conn.execute("SELECT event_type, COUNT(*) FROM events GROUP BY event_type").fetchall())
        by_status = dict(conn.execute("SELECT status, COUNT(*) FROM events GROUP BY status").fetchall())
        avg_duration = conn.execute(
            "SELECT AVG(duration_ms) FROM events WHERE duration_ms IS NOT NULL"
        ).fetchone()[0]
    finally:
        conn.close()
    return {
        "total_events": total, "by_source": by_source, "by_event_type": by_event_type,
        "by_status": by_status, "avg_duration_ms": avg_duration,
    }


def op_backfill():
    """Reconcile the queryable SQLite index against the permanent JSONL
    ledger. Mirrors memory_core.op_backfill() — the same recovery this
    organ's own module docstring already claims to have ("storage
    mirrors Memory's own established pattern exactly, on purpose") but
    didn't actually implement. Covers two real cases: op_emit()'s
    SQLite insert failing after its JSONL append already succeeded
    (leaving that one event unindexed), and the .sqlite3 file itself
    being deleted or corrupted (get_db() just recreates an empty
    table — every prior event would otherwise become permanently
    unqueryable despite still being safely on disk in the ledger).
    A corrupted trailing ledger line (process killed mid-write) is
    reported via the same failed/errors shape as any other per-entry
    problem, not allowed to abort the whole run."""
    ensure_data_dir()
    if not LEDGER_PATH.exists():
        return {"backfilled": 0, "already_indexed": 0, "failed": 0, "errors": []}

    conn = get_db()
    try:
        already = {row[0] for row in conn.execute("SELECT event_id FROM events")}

        backfilled, failed, errors = 0, 0, []
        for line in LEDGER_PATH.read_text(encoding="utf-8").strip().splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as e:
                failed += 1
                errors.append({"line": line[:80], "error": f"unparseable ledger line: {e}"})
                continue

            if event.get("event_id") in already:
                continue

            try:
                conn.execute(
                    """INSERT INTO events (event_id, timestamp, monotonic_time, event_type, source,
                                            actor, correlation_id, parent_event_id, severity, payload,
                                            result, duration_ms, status, provenance)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (event["event_id"], event["timestamp"], event["monotonic_time"], event["event_type"],
                     event["source"], event.get("actor"), event.get("correlation_id"),
                     event.get("parent_event_id"), event["severity"], json.dumps(event.get("payload") or {}),
                     json.dumps(event["result"]) if event.get("result") is not None else None,
                     event.get("duration_ms"), event["status"],
                     json.dumps(event["provenance"]) if event.get("provenance") is not None else None),
                )
                already.add(event["event_id"])
                backfilled += 1
            except (KeyError, sqlite3.Error) as e:
                failed += 1
                errors.append({"line": line[:80], "error": f"could not index: {e}"})

        conn.commit()
    finally:
        conn.close()

    return {"backfilled": backfilled, "already_indexed": len(already) - backfilled, "failed": failed,
            "errors": errors}
