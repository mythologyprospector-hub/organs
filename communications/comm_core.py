"""
comm_core.py — the Communications organ: pub/sub bus + dispatch.

Two different problems, sharing one store:

  BUS (publish/consume): "this happened, whoever cares can react."
  Broadcast semantics — every consumer sees every event on a topic it's
  watching, independently. Not a work queue (nobody "claims" an event
  and removes it for everyone else) — each consumer has its own cursor
  into the topic's history.

  DISPATCH: "one of you handle this." Generalized from group_chat.py's
  round_robin/irc modes — back then it was "which agent speaks next in
  this chat," here it's "which organ (or which of several) should get
  this," with the same handful of strategies: round_robin (take turns,
  fairly), random, or broadcast (all of them, when that's the point).

Pull-based, not push: consumers poll for what's new since their cursor
rather than Communications calling back into every organ's own inbound
endpoint. Simpler, and it's the same pattern every organ already uses to
talk to the Registry.
"""
import json
import os
import random
import sqlite3
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("COMM_DATA_DIR", str(HERE / "data"))).expanduser()
DB_PATH = DATA_DIR / "bus.sqlite3"

VALID_DISPATCH_STRATEGIES = {"round_robin", "random", "broadcast"}


class CommError(Exception):
    """Raised on any failure the API layer should turn into an OrganError."""


def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def get_db():
    ensure_data_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            topic TEXT NOT NULL,
            event_type TEXT NOT NULL,
            publisher TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_topic ON events(topic, id)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS consumer_cursors (
            consumer TEXT NOT NULL,
            topic TEXT NOT NULL,
            last_event_id INTEGER NOT NULL DEFAULT 0,
            updated_ts REAL NOT NULL,
            PRIMARY KEY (consumer, topic)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dispatch_state (
            dispatch_key TEXT PRIMARY KEY,
            last_index INTEGER NOT NULL DEFAULT -1,
            updated_ts REAL NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def op_doctor():
    ensure_data_dir()
    try:
        conn = get_db()
        conn.execute("SELECT 1")
        conn.close()
        db_ok = True
        detail = f"sqlite OK at {DB_PATH}"
    except Exception as e:
        db_ok = False
        detail = str(e)
    return {"data_dir": str(DATA_DIR), "data_dir_writable": os.access(DATA_DIR, os.W_OK), "db_ok": db_ok, "detail": detail}


def check_db():
    """Cheap health-check hook for organ_base."""
    try:
        conn = get_db()
        conn.execute("SELECT 1")
        conn.close()
        return True, f"sqlite OK at {DB_PATH}"
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# bus: publish / peek / consume
# ---------------------------------------------------------------------------

def op_publish(topic: str, event_type: str, payload: dict, publisher: str):
    if not topic or not topic.strip():
        raise CommError("topic must not be empty")
    if not publisher or not publisher.strip():
        raise CommError("publisher must not be empty")

    conn = get_db()
    try:
        now = time.time()
        conn.execute(
            "INSERT INTO events (ts, topic, event_type, publisher, payload) VALUES (?, ?, ?, ?, ?)",
            (now, topic, event_type, publisher, json.dumps(payload)),
        )
        conn.commit()
        event_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    finally:
        conn.close()

    return {"id": event_id, "ts": now, "topic": topic, "event_type": event_type, "publisher": publisher, "payload": payload}


def op_list_topics():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT topic, COUNT(*), MAX(ts), MAX(id) FROM events GROUP BY topic ORDER BY topic"
        ).fetchall()
    finally:
        conn.close()
    return [{"topic": r[0], "event_count": r[1], "latest_ts": r[2], "latest_event_id": r[3]} for r in rows]


def op_peek(topic: str, since_id: int = 0, limit: int = 50):
    """Read events on a topic WITHOUT advancing any consumer's cursor —
    for debugging/inspection, not the normal consumption path."""
    if limit < 1:
        raise CommError("limit must be at least 1")
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, ts, topic, event_type, publisher, payload FROM events "
            "WHERE topic = ? AND id > ? ORDER BY id ASC LIMIT ?",
            (topic, since_id, limit),
        ).fetchall()
    finally:
        conn.close()
    return [
        {"id": r[0], "ts": r[1], "topic": r[2], "event_type": r[3], "publisher": r[4], "payload": json.loads(r[5])}
        for r in rows
    ]


def op_consume(consumer: str, topics: list[str], limit: int = 50):
    """The normal path: give `consumer` everything new since ITS OWN
    cursor on each requested topic, then advance that cursor. Every
    consumer sees every event independently — this is broadcast, not a
    queue where one consumer's read removes it for others."""
    if not consumer or not consumer.strip():
        raise CommError("consumer must not be empty")
    if not topics:
        raise CommError("must specify at least one topic")
    if limit < 1:
        raise CommError("limit must be at least 1")

    conn = get_db()
    try:
        all_events = []
        has_more = False

        for topic in topics:
            cur_row = conn.execute(
                "SELECT last_event_id FROM consumer_cursors WHERE consumer = ? AND topic = ?", (consumer, topic)
            ).fetchone()
            since_id = cur_row[0] if cur_row else 0

            rows = conn.execute(
                "SELECT id, ts, topic, event_type, publisher, payload FROM events "
                "WHERE topic = ? AND id > ? ORDER BY id ASC LIMIT ?",
                (topic, since_id, limit),
            ).fetchall()

            if len(rows) == limit:
                # there might be more beyond this page on this topic
                more_row = conn.execute(
                    "SELECT COUNT(*) FROM events WHERE topic = ? AND id > ?", (topic, rows[-1][0])
                ).fetchone()
                if more_row[0] > 0:
                    has_more = True

            for r in rows:
                all_events.append({
                    "id": r[0], "ts": r[1], "topic": r[2], "event_type": r[3], "publisher": r[4], "payload": json.loads(r[5]),
                })

            if rows:
                new_cursor = rows[-1][0]
                now = time.time()
                conn.execute(
                    "INSERT INTO consumer_cursors (consumer, topic, last_event_id, updated_ts) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(consumer, topic) DO UPDATE SET last_event_id = ?, updated_ts = ?",
                    (consumer, topic, new_cursor, now, new_cursor, now),
                )

        conn.commit()
    finally:
        conn.close()

    all_events.sort(key=lambda e: e["id"])
    return {"events": all_events, "count": len(all_events), "has_more": has_more}


def op_list_consumers():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT consumer, topic, last_event_id, updated_ts FROM consumer_cursors ORDER BY consumer, topic"
        ).fetchall()
    finally:
        conn.close()
    return [{"consumer": r[0], "topic": r[1], "last_event_id": r[2], "updated_ts": r[3]} for r in rows]


def op_reset_consumer(consumer: str, topic: str, to_id: int = 0):
    """Rewind a consumer's cursor — for replay/debugging. Doesn't touch
    the events themselves, just where this one consumer is reading from."""
    conn = get_db()
    try:
        now = time.time()
        conn.execute(
            "INSERT INTO consumer_cursors (consumer, topic, last_event_id, updated_ts) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(consumer, topic) DO UPDATE SET last_event_id = ?, updated_ts = ?",
            (consumer, topic, to_id, now, to_id, now),
        )
        conn.commit()
    finally:
        conn.close()
    return {"consumer": consumer, "topic": topic, "last_event_id": to_id}


# ---------------------------------------------------------------------------
# dispatch: "one of you handle this" — round_robin / random / broadcast
# ---------------------------------------------------------------------------

def op_dispatch(dispatch_key: str, candidates: list[str], strategy: str = "round_robin"):
    if not candidates:
        raise CommError("candidates must not be empty")
    if strategy not in VALID_DISPATCH_STRATEGIES:
        raise CommError(f"strategy must be one of {sorted(VALID_DISPATCH_STRATEGIES)}, got {strategy!r}")

    if strategy == "broadcast":
        return {"strategy": strategy, "selected": list(candidates)}

    if strategy == "random":
        return {"strategy": strategy, "selected": [random.choice(candidates)]}

    # round_robin: fair rotation, remembered per dispatch_key so repeated
    # calls with the same key actually take turns rather than restarting
    # from 0 every time.
    conn = get_db()
    try:
        row = conn.execute("SELECT last_index FROM dispatch_state WHERE dispatch_key = ?", (dispatch_key,)).fetchone()
        last_index = row[0] if row else -1
        next_index = (last_index + 1) % len(candidates)

        now = time.time()
        conn.execute(
            "INSERT INTO dispatch_state (dispatch_key, last_index, updated_ts) VALUES (?, ?, ?) "
            "ON CONFLICT(dispatch_key) DO UPDATE SET last_index = ?, updated_ts = ?",
            (dispatch_key, next_index, now, next_index, now),
        )
        conn.commit()
    finally:
        conn.close()

    return {"strategy": strategy, "selected": [candidates[next_index]], "rotation_index": next_index}


def op_reset_dispatch(dispatch_key: str):
    conn = get_db()
    try:
        conn.execute("DELETE FROM dispatch_state WHERE dispatch_key = ?", (dispatch_key,))
        conn.commit()
    finally:
        conn.close()
    return {"dispatch_key": dispatch_key, "reset": True}
