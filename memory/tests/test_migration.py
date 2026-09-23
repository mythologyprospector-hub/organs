import sqlite3
import struct
import time


def test_get_db_migrates_original_bare_schema(mc, tmp_path):
    """Simulates the very first llama_memory.py schema (just id, ts, text,
    tags, model, dim, embedding — no salience, no epistemic fields) and
    confirms get_db() brings it forward without error or data loss."""
    mc.ensure_data_dir()
    raw_conn = sqlite3.connect(mc.DB_PATH)
    raw_conn.execute(
        """
        CREATE TABLE entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            text TEXT NOT NULL,
            tags TEXT NOT NULL,
            model TEXT NOT NULL,
            dim INTEGER NOT NULL,
            embedding BLOB NOT NULL
        )
        """
    )
    old_ts = time.time() - 1000
    vec = [0.1] * 8
    raw_conn.execute(
        "INSERT INTO entries (ts, text, tags, model, dim, embedding) VALUES (?, ?, ?, ?, ?, ?)",
        (old_ts, "an old memory from before salience existed", "[]", "nomic-embed-text", 8, struct.pack("8f", *vec)),
    )
    raw_conn.commit()
    raw_conn.close()

    # this is the actual migration path — same call every op uses
    conn = mc.get_db()
    row = conn.execute(
        "SELECT text, access_count, last_accessed, pinned, provenance, witness, "
        "confidence_base, last_confirmed, owner FROM entries"
    ).fetchone()
    conn.close()

    text, access_count, last_accessed, pinned, provenance, witness, confidence_base, last_confirmed, owner = row
    assert text == "an old memory from before salience existed"
    assert access_count == 0
    assert last_accessed == old_ts  # backfilled from ts, not left NULL
    assert pinned == 0
    assert provenance == "unspecified"
    assert witness == "direct"
    assert confidence_base == 0.8
    assert last_confirmed == old_ts  # backfilled too
    assert owner == "user"

    # and it's fully usable through the normal API, not just readable
    entry = mc.op_get_entry(1)
    assert entry["confidence"] <= 0.8  # decayed some, since old_ts is in the past
    assert entry["archived"] is False
