"""
memory_core.py — the Memory organ's full model.

This answers GOAL.md's question set by NOT building 21 separate memory
systems. Most of those questions are fields that belong on every record
(provenance, witness, confidence, permissions, time) — not new storage.
A small number of things genuinely have different lifecycles and get
their own table:

    Scars       — permanent behavioral mutations ("the lesson survives
                  even when the event is forgotten"). Write-once, never
                  decay, never archive. Corrections append a new scar
                  and mark the old one superseded — nothing is silently
                  overwritten. This is "canon": once a scar is accepted,
                  it stays true until something explicitly supersedes it.
    Promises    — a state machine (pending -> fulfilled/broken/cancelled),
                  not a fact that's just true or false.
    Unknowable  — a placeholder that deliberately stores NO content:
                  "something exists here, I can't access it, here's why."
    Relations   — one lightweight edge table connecting any two records
                  (entries/facts/scars/promises/unknowables), used for
                  both contradictions and general "this relates to that."

Everything that sounds like a new subsystem but isn't gets folded in:
  - Confidence decay reuses the EXACT SAME half-life math as salience
    decay — they're the same mechanism (recency-weighted decline unless
    reinforced) applied to two different questions ("how findable" vs
    "how sure we are it's still true").
  - "Write fast, sort slow" is just the existing ledger -> consolidation
    pipeline, plus scar/relation proposals following the same
    propose-then-human-decides gate as fact consolidation already uses.
    Nothing cheap/local ever commits something permanent unsupervised.

Layers, for orientation:
    Layer 0   ledger.jsonl              — permanent, append-only, never pruned
    Layer 1   entries (sqlite)          — active, searchable, salience-scored
    Layer 1.5 archived_entries (sqlite) — "forgotten" = here, not deleted
    Layer 2   facts.jsonl               — consolidated, confidence-scored
    Layer 2.5 scars.jsonl               — permanent behavioral mutations
    Layer 3   promises / unknowable / relations (sqlite) — structured state
"""
import json
import math
import os
import sqlite3
import struct
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("LLAMA_MEMORY_DIR", str(HERE / "data"))).expanduser()
LEDGER_PATH = DATA_DIR / "ledger.jsonl"
DB_PATH = DATA_DIR / "vectors.sqlite3"
PROPOSED_FACTS_PATH = DATA_DIR / "proposed_facts.jsonl"
FACTS_PATH = DATA_DIR / "facts.jsonl"
PROPOSED_SCARS_PATH = DATA_DIR / "proposed_scars.jsonl"
SCARS_PATH = DATA_DIR / "scars.jsonl"

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
CONSOLIDATE_MODEL = os.environ.get("CONSOLIDATE_MODEL", "llama3.1:8b")

DUPLICATE_WARN_THRESHOLD = 0.95

# --- decay tuning (salience AND confidence share this mechanism) ----------
SALIENCE_HALF_LIFE_DAYS = float(os.environ.get("SALIENCE_HALF_LIFE_DAYS", "30"))
SALIENCE_FREQUENCY_SATURATION = float(os.environ.get("SALIENCE_FREQUENCY_SATURATION", "20"))
SALIENCE_CONSOLIDATION_BOOST = 0.15
SALIENCE_RECENCY_WEIGHT = 0.6
SALIENCE_FREQUENCY_WEIGHT = 0.4

CONFIDENCE_HALF_LIFE_DAYS = float(os.environ.get("CONFIDENCE_HALF_LIFE_DAYS", "90"))
CONFIDENCE_FLOOR = 0.05  # unlike salience, confidence never fully bottoms out —
                          # "decayed to unsure" isn't the same claim as "known false"

RECALL_SIMILARITY_WEIGHT = float(os.environ.get("RECALL_SIMILARITY_WEIGHT", "0.75"))
RECALL_SALIENCE_WEIGHT = float(os.environ.get("RECALL_SALIENCE_WEIGHT", "0.25"))

PRUNE_DEFAULT_THRESHOLD = float(os.environ.get("PRUNE_DEFAULT_THRESHOLD", "0.15"))
PRUNE_MIN_AGE_DAYS = float(os.environ.get("PRUNE_MIN_AGE_DAYS", "7"))

VALID_WITNESS = {"direct", "secondhand", "hearsay", "inferred"}
VALID_PROMISE_STATUS = {"pending", "fulfilled", "broken", "cancelled"}
VALID_RELATION_TYPES = {"contradicts", "relates_to", "supersedes", "caused_by", "supports"}
VALID_RECORD_TYPES = {"entry", "fact", "scar", "promise", "unknowable"}

CONSOLIDATION_PROMPT_TEMPLATE = """You are distilling a set of related notes into ONE current, accurate fact.

Notes below are in chronological order (oldest first). If they conflict — a later note updates or contradicts an earlier one — treat the LATER note as current and say so explicitly rather than blending them into a compromise that isn't true. If they simply repeat or reinforce each other, distill them into one clean sentence.

Notes:
{notes}

Respond with ONLY the distilled fact as 1-2 plain sentences. No preamble, no "Based on the notes", no bullet points."""

ENTRY_COLUMNS = (
    "id, ts, text, tags, model, dim, embedding, access_count, last_accessed, pinned, "
    "provenance, witness, confidence_base, last_confirmed, owner, may_reveal, may_modify, may_delete"
)


class MemoryError(Exception):
    """Raised on any failure the API layer should turn into an OrganError."""


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------

def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not LEDGER_PATH.exists():
        LEDGER_PATH.touch()


def _migrate_add_column(conn, table, coldef):
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {coldef}")
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise


def get_db():
    ensure_data_dir()
    conn = sqlite3.connect(DB_PATH)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entries (
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
    # v2 (salience) columns
    _migrate_add_column(conn, "entries", "access_count INTEGER NOT NULL DEFAULT 0")
    _migrate_add_column(conn, "entries", "last_accessed REAL")
    _migrate_add_column(conn, "entries", "pinned INTEGER NOT NULL DEFAULT 0")
    # v3 (epistemic) columns — fields, not new subsystems
    _migrate_add_column(conn, "entries", "provenance TEXT NOT NULL DEFAULT 'unspecified'")
    _migrate_add_column(conn, "entries", "witness TEXT NOT NULL DEFAULT 'direct'")
    _migrate_add_column(conn, "entries", "confidence_base REAL NOT NULL DEFAULT 0.8")
    _migrate_add_column(conn, "entries", "last_confirmed REAL")
    _migrate_add_column(conn, "entries", "owner TEXT NOT NULL DEFAULT 'user'")
    _migrate_add_column(conn, "entries", "may_reveal INTEGER NOT NULL DEFAULT 1")
    _migrate_add_column(conn, "entries", "may_modify INTEGER NOT NULL DEFAULT 1")
    _migrate_add_column(conn, "entries", "may_delete INTEGER NOT NULL DEFAULT 1")
    conn.execute("UPDATE entries SET last_accessed = ts WHERE last_accessed IS NULL")
    conn.execute("UPDATE entries SET last_confirmed = ts WHERE last_confirmed IS NULL")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS archived_entries (
            id INTEGER PRIMARY KEY,
            ts REAL NOT NULL,
            text TEXT NOT NULL,
            tags TEXT NOT NULL,
            model TEXT NOT NULL,
            dim INTEGER NOT NULL,
            embedding BLOB NOT NULL,
            access_count INTEGER NOT NULL DEFAULT 0,
            last_accessed REAL,
            pinned INTEGER NOT NULL DEFAULT 0,
            provenance TEXT NOT NULL DEFAULT 'unspecified',
            witness TEXT NOT NULL DEFAULT 'direct',
            confidence_base REAL NOT NULL DEFAULT 0.8,
            last_confirmed REAL,
            owner TEXT NOT NULL DEFAULT 'user',
            may_reveal INTEGER NOT NULL DEFAULT 1,
            may_modify INTEGER NOT NULL DEFAULT 1,
            may_delete INTEGER NOT NULL DEFAULT 1,
            archived_ts REAL NOT NULL,
            archived_reason TEXT NOT NULL
        )
        """
    )

    # --- Promises: a state machine, not a fact ----------------------------
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS promises (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_created REAL NOT NULL,
            text TEXT NOT NULL,
            owner TEXT NOT NULL,
            condition_text TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            ts_resolved REAL,
            resolution_note TEXT
        )
        """
    )

    # --- Unknowable: stores that something exists, never stores what ------
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS unknowable (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            description TEXT NOT NULL,
            reason TEXT NOT NULL,
            confidence_exists REAL NOT NULL,
            owner_to_request TEXT,
            status TEXT NOT NULL DEFAULT 'inaccessible',
            resolved_entry_id INTEGER,
            resolved_ts REAL
        )
        """
    )

    # --- Relations: one edge table for contradictions + everything else ---
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            id_a INTEGER NOT NULL,
            type_a TEXT NOT NULL,
            id_b INTEGER NOT NULL,
            type_b TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            note TEXT,
            status TEXT NOT NULL DEFAULT 'unresolved',
            resolved_which TEXT,
            resolution_note TEXT,
            resolved_ts REAL
        )
        """
    )

    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# ollama calls
# ---------------------------------------------------------------------------

def ollama_embed(text: str, model: str = None, timeout: float = 30.0, retries: int = 1):
    model = model or EMBED_MODEL
    url = f"{OLLAMA_HOST}/api/embeddings"
    payload = json.dumps({"model": model, "prompt": text}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.URLError as e:
            if attempt < retries:
                continue
            raise MemoryError(f"Could not reach Ollama at {OLLAMA_HOST} ({e}). Is `ollama serve` running?") from e
    embedding = body.get("embedding")
    if not embedding:
        raise MemoryError(f"Ollama responded but returned no embedding. Raw response: {body}")
    return embedding


def ollama_generate(prompt: str, model: str = None, timeout: float = 90.0, retries: int = 1):
    model = model or CONSOLIDATE_MODEL
    url = f"{OLLAMA_HOST}/api/generate"
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.URLError as e:
            if attempt < retries:
                continue
            raise MemoryError(
                f"Could not reach Ollama at {OLLAMA_HOST} for generation ({e}). "
                f"Is `ollama serve` running, and is {model!r} pulled?"
            ) from e
    text = body.get("response")
    if text is None:
        raise MemoryError(f"Ollama responded but returned no text. Raw response: {body}")
    return text.strip()


def ping_ollama():
    try:
        req = urllib.request.Request(f"{OLLAMA_HOST}/api/tags")
        with urllib.request.urlopen(req, timeout=3.0):
            return True, f"reachable at {OLLAMA_HOST}"
    except Exception as e:
        return False, f"unreachable at {OLLAMA_HOST} ({e})"


# ---------------------------------------------------------------------------
# clustering (unchanged)
# ---------------------------------------------------------------------------

class UnionFind:
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def pack_vec(vec):
    return struct.pack(f"{len(vec)}f", *vec)


def unpack_vec(blob, dim):
    return struct.unpack(f"{dim}f", blob)


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def cluster_entries(rows, threshold):
    n = len(rows)
    vecs = [unpack_vec(r[5], r[4]) for r in rows]
    uf = UnionFind(n)
    for i in range(n):
        for j in range(i + 1, n):
            if cosine(vecs[i], vecs[j]) >= threshold:
                uf.union(i, j)

    groups = {}
    for i in range(n):
        root = uf.find(i)
        groups.setdefault(root, []).append(i)

    clusters = []
    for idxs in groups.values():
        members = []
        for i in idxs:
            id_, ts, text, tags, dim, blob = rows[i]
            members.append({"id": id_, "ts": ts, "text": text, "tags": json.loads(tags)})
        members.sort(key=lambda m: m["ts"])
        clusters.append(members)
    clusters.sort(key=len, reverse=True)
    return clusters


def build_consolidation_prompt(members):
    lines = []
    for m in members:
        when = time.strftime("%Y-%m-%d", time.localtime(m["ts"]))
        lines.append(f"- [{when}] {m['text']}")
    return CONSOLIDATION_PROMPT_TEMPLATE.format(notes="\n".join(lines))


def load_jsonl(path):
    """Skips any line that fails to parse as JSON — e.g. a process killed
    mid-write leaving a truncated final line — rather than letting one
    bad line take down every one of this function's 13 call sites across
    facts, scars, and proposals. Same defense as load_state()/
    load_history() apply to their own persistence files, extended here
    since load_jsonl() is the shared helper backing most of them."""
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def write_jsonl(path, records):
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def most_similar(conn, vec):
    rows = conn.execute("SELECT text, dim, embedding FROM entries").fetchall()
    if not rows:
        return None, None
    best_score, best_text = -1.0, None
    for text, dim, blob in rows:
        score = cosine(vec, unpack_vec(blob, dim))
        if score > best_score:
            best_score, best_text = score, text
    return best_score, best_text


def indexed_keys(conn):
    return {(ts, text) for (ts, text) in conn.execute("SELECT ts, text FROM entries")}


# ---------------------------------------------------------------------------
# decay — ONE mechanism, used for both salience and confidence
# ---------------------------------------------------------------------------

def _decay(base: float, elapsed_days: float, half_life_days: float, floor: float = 0.0) -> float:
    if half_life_days <= 0:
        return base
    decayed = base * (0.5 ** (elapsed_days / half_life_days))
    return max(floor, min(1.0, decayed))


def _consolidated_ids():
    ids = set()
    for fact in load_jsonl(FACTS_PATH):
        ids.update(fact.get("source_ids", []))
    return ids


def compute_salience(access_count, last_accessed, pinned, consolidated, now=None):
    """How findable — driven by recall frequency, not by truth."""
    now = now if now is not None else time.time()

    if pinned:
        return {"salience": 1.0, "pinned": True, "recency": None, "frequency": None, "consolidation_boost": None}

    last_accessed = last_accessed if last_accessed is not None else now
    days_since = max(0.0, (now - last_accessed) / 86400.0)
    recency = 0.5 ** (days_since / SALIENCE_HALF_LIFE_DAYS) if SALIENCE_HALF_LIFE_DAYS > 0 else 1.0
    frequency = min(1.0, math.log1p(access_count) / math.log1p(SALIENCE_FREQUENCY_SATURATION))
    boost = SALIENCE_CONSOLIDATION_BOOST if consolidated else 0.0
    raw = (SALIENCE_RECENCY_WEIGHT * recency) + (SALIENCE_FREQUENCY_WEIGHT * frequency) + boost
    salience = max(0.0, min(1.0, raw))

    return {
        "salience": round(salience, 4), "pinned": False,
        "recency": round(recency, 4), "frequency": round(frequency, 4),
        "consolidation_boost": boost, "days_since_access": round(days_since, 2),
        "access_count": access_count,
    }


def compute_confidence(confidence_base, last_confirmed, now=None):
    """How sure we are it's still TRUE — decays the same shape as
    salience, but never bottoms out at zero (decayed-to-unsure isn't the
    same claim as known-false), and is reinforced by confirmation or
    consolidation, not by being searched."""
    now = now if now is not None else time.time()
    last_confirmed = last_confirmed if last_confirmed is not None else now
    days_since = max(0.0, (now - last_confirmed) / 86400.0)
    current = _decay(confidence_base, days_since, CONFIDENCE_HALF_LIFE_DAYS, floor=CONFIDENCE_FLOOR)
    return {"confidence": round(current, 4), "confidence_base": confidence_base, "days_since_confirmed": round(days_since, 2)}


# ---------------------------------------------------------------------------
# Layer 0/1 operations — ledger, recall, salience/forgetting
# ---------------------------------------------------------------------------

def op_doctor():
    ok, detail = ping_ollama()
    result = {"ollama_host": OLLAMA_HOST, "embed_model": EMBED_MODEL, "ollama_reachable": ok, "detail": detail}
    if ok:
        try:
            vec = ollama_embed("health check")
            result["embedding_ok"] = True
            result["embedding_dim"] = len(vec)
        except MemoryError as e:
            result["embedding_ok"] = False
            result["embedding_error"] = str(e)
    ensure_data_dir()
    result["data_dir"] = str(DATA_DIR)
    result["data_dir_writable"] = os.access(DATA_DIR, os.W_OK)
    return result


def op_add(text: str, tags: list[str] | None = None, provenance: str = "unspecified",
           witness: str = "direct", confidence: float = 0.8, owner: str = "user",
           may_reveal: bool = True, may_modify: bool = True, may_delete: bool = True):
    tags = tags or []
    if witness not in VALID_WITNESS:
        raise MemoryError(f"witness must be one of {sorted(VALID_WITNESS)}, got {witness!r}")
    if not (0.0 <= confidence <= 1.0):
        raise MemoryError(f"confidence must be between 0 and 1, got {confidence}")
    ts = time.time()

    ensure_data_dir()
    with LEDGER_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": ts, "text": text, "tags": tags, "provenance": provenance, "witness": witness,
            "confidence": confidence, "owner": owner,
            "permissions": {"may_reveal": may_reveal, "may_modify": may_modify, "may_delete": may_delete},
        }) + "\n")

    try:
        vec = ollama_embed(text)
    except MemoryError as e:
        return {"stored": True, "embedded": False, "warning": f"saved to ledger, embedding failed: {e}"}

    conn = get_db()
    score, existing_text = most_similar(conn, vec)
    duplicate_of = None
    if score is not None and score >= DUPLICATE_WARN_THRESHOLD:
        duplicate_of = {"score": round(score, 3), "text": existing_text}

    conn.execute(
        "INSERT INTO entries (ts, text, tags, model, dim, embedding, access_count, last_accessed, pinned, "
        "provenance, witness, confidence_base, last_confirmed, owner, may_reveal, may_modify, may_delete) "
        "VALUES (?, ?, ?, ?, ?, ?, 0, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ts, text, json.dumps(tags), EMBED_MODEL, len(vec), pack_vec(vec), ts,
         provenance, witness, confidence, ts, owner, int(may_reveal), int(may_modify), int(may_delete)),
    )
    conn.commit()
    entry_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()

    return {"stored": True, "embedded": True, "id": entry_id, "dim": len(vec), "possible_duplicate": duplicate_of}


def op_recall(query: str, k: int = 5, include_archived: bool = False,
              sim_weight: float = None, sal_weight: float = None):
    sim_weight = RECALL_SIMILARITY_WEIGHT if sim_weight is None else sim_weight
    sal_weight = RECALL_SALIENCE_WEIGHT if sal_weight is None else sal_weight

    qvec = ollama_embed(query)

    conn = get_db()
    rows = conn.execute(f"SELECT {ENTRY_COLUMNS} FROM entries").fetchall()

    consolidated = _consolidated_ids()
    now = time.time()

    def _row_result(row, archived):
        (id_, ts, text, tags, model, dim, blob, access_count, last_accessed, pinned,
         provenance, witness, confidence_base, last_confirmed, owner, may_reveal, may_modify, may_delete) = row
        vec = unpack_vec(blob, dim)
        sim = cosine(qvec, vec)
        sal = compute_salience(access_count, last_accessed, bool(pinned), id_ in consolidated, now)
        conf = compute_confidence(confidence_base, last_confirmed, now)
        combined = (sim_weight * sim) + (sal_weight * sal["salience"])
        return {
            "id": id_, "ts": ts, "text": text, "tags": json.loads(tags),
            "similarity": round(sim, 4), "salience": sal["salience"], "confidence": conf["confidence"],
            "combined_score": round(combined, 4), "pinned": bool(pinned), "archived": archived,
            "provenance": provenance, "witness": witness, "owner": owner,
        }

    scored = [_row_result(r, False) for r in rows]

    if include_archived:
        arows = conn.execute(f"SELECT {ENTRY_COLUMNS} FROM archived_entries").fetchall()
        scored += [_row_result(r, True) for r in arows]

    scored.sort(key=lambda r: r["combined_score"], reverse=True)
    top = scored[:k]

    top_active_ids = [r["id"] for r in top if not r["archived"]]
    if top_active_ids:
        placeholders = ",".join("?" * len(top_active_ids))
        conn.execute(
            f"UPDATE entries SET access_count = access_count + 1, last_accessed = ? WHERE id IN ({placeholders})",
            (now, *top_active_ids),
        )
        conn.commit()

    conn.close()
    return top


def op_confirm(entry_id: int):
    """Explicit 'this is still true' signal — resets the confidence decay
    clock. Distinct from recall's salience reinforcement: being asked
    about something makes it findable; being CONFIRMED makes it trusted."""
    conn = get_db()
    now = time.time()
    cur = conn.execute("UPDATE entries SET last_confirmed = ? WHERE id = ?", (now, entry_id))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise MemoryError(f"no active entry with id {entry_id}")
    return {"id": entry_id, "confirmed": True, "ts": now}


def op_list(n: int = 20):
    """Skips any trailing line that fails to parse as JSON — same defense
    load_jsonl() applies to facts/scars/proposals, extended to the
    ledger itself since this is the single most-read entry point into
    it (including by Reflection's own context fetch)."""
    ensure_data_dir()
    if not LEDGER_PATH.exists():
        return []
    lines = LEDGER_PATH.read_text(encoding="utf-8").strip().splitlines()
    selected = lines[-n:] if n > 0 else []
    entries = []
    for line in selected:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def op_stats():
    ensure_data_dir()
    ledger_count = sum(1 for _ in LEDGER_PATH.open("r", encoding="utf-8")) if LEDGER_PATH.exists() else 0

    conn = get_db()
    (indexed_count,) = conn.execute("SELECT COUNT(*) FROM entries").fetchone()
    (archived_count,) = conn.execute("SELECT COUNT(*) FROM archived_entries").fetchone()
    (pinned_count,) = conn.execute("SELECT COUNT(*) FROM entries WHERE pinned = 1").fetchone()
    (scar_count,) = (len(load_jsonl(SCARS_PATH)),)
    (promise_pending,) = conn.execute("SELECT COUNT(*) FROM promises WHERE status = 'pending'").fetchone()
    (unknowable_count,) = conn.execute("SELECT COUNT(*) FROM unknowable WHERE status = 'inaccessible'").fetchone()
    (relation_unresolved,) = conn.execute("SELECT COUNT(*) FROM relations WHERE status = 'unresolved'").fetchone()
    conn.close()

    return {
        "ledger_entries": ledger_count,
        "indexed_entries": indexed_count,
        "unembedded": max(0, ledger_count - indexed_count - archived_count),
        "archived_entries": archived_count,
        "pinned_entries": pinned_count,
        "active_scars": scar_count,
        "pending_promises": promise_pending,
        "open_unknowables": unknowable_count,
        "unresolved_relations": relation_unresolved,
    }


def op_backfill():
    ensure_data_dir()
    if not LEDGER_PATH.exists():
        return {"backfilled": 0, "failed": 0, "errors": []}

    conn = get_db()
    already = indexed_keys(conn)
    already |= {(ts, text) for (ts, text) in conn.execute("SELECT ts, text FROM archived_entries")}

    lines = LEDGER_PATH.read_text(encoding="utf-8").strip().splitlines()
    missing = []
    parse_failed, parse_errors = 0, []
    for line in lines:
        # A corrupted trailing line (process killed mid-write) must not
        # abort backfill entirely — that would be especially perverse
        # here, since backfill exists as a recovery tool and shouldn't
        # be taken down by the exact kind of damage it might be run to
        # recover from. Reported through the same failed/errors shape
        # the embedding step below already uses, not silently dropped.
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as e:
            parse_failed += 1
            parse_errors.append({"text": line[:80], "error": f"unparseable ledger line: {e}"})
            continue
        key = (entry["ts"], entry["text"])
        if key not in already:
            missing.append(entry)

    if not missing:
        conn.close()
        return {"backfilled": 0, "failed": parse_failed, "errors": parse_errors}

    ok, failed, errors = 0, parse_failed, list(parse_errors)
    for entry in missing:
        try:
            vec = ollama_embed(entry["text"])
        except MemoryError as e:
            failed += 1
            errors.append({"text": entry["text"][:80], "error": str(e)})
            continue
        perms = entry.get("permissions", {})
        conn.execute(
            "INSERT INTO entries (ts, text, tags, model, dim, embedding, access_count, last_accessed, pinned, "
            "provenance, witness, confidence_base, last_confirmed, owner, may_reveal, may_modify, may_delete) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?)",
            (entry["ts"], entry["text"], json.dumps(entry.get("tags", [])), EMBED_MODEL, len(vec), pack_vec(vec),
             entry["ts"], entry.get("provenance", "unspecified"), entry.get("witness", "direct"),
             entry.get("confidence", 0.8), entry["ts"], entry.get("owner", "user"),
             int(perms.get("may_reveal", True)), int(perms.get("may_modify", True)), int(perms.get("may_delete", True))),
        )
        conn.commit()
        ok += 1

    conn.close()
    return {"backfilled": ok, "failed": failed, "errors": errors}


def op_consolidate(threshold: float = 0.80, min_witnesses: int = 3):
    conn = get_db()
    rows = conn.execute("SELECT id, ts, text, tags, dim, embedding FROM entries").fetchall()
    conn.close()

    if len(rows) < min_witnesses:
        return {"clusters": 0, "proposals_created": 0, "note": f"only {len(rows)} entries indexed, need {min_witnesses}+"}

    clusters = cluster_entries(rows, threshold)
    qualifying = [c for c in clusters if len(c) >= min_witnesses]

    existing = load_jsonl(PROPOSED_FACTS_PATH)
    already_proposed_id_sets = {tuple(sorted(p["source_ids"])) for p in existing}

    created = []
    for members in qualifying:
        ids = tuple(sorted(m["id"] for m in members))
        if ids in already_proposed_id_sets:
            continue

        prompt = build_consolidation_prompt(members)
        try:
            distilled = ollama_generate(prompt)
        except MemoryError as e:
            created.append({"error": str(e), "cluster_size": len(members)})
            continue

        proposal = {
            "id": uuid.uuid4().hex[:8],
            "proposed_ts": time.time(),
            "source_ids": [m["id"] for m in members],
            "source_texts": [m["text"] for m in members],
            "cluster_size": len(members),
            "proposed_fact": distilled,
            "status": "pending",
        }
        existing.append(proposal)
        created.append(proposal)

    if any("id" in c for c in created):
        write_jsonl(PROPOSED_FACTS_PATH, existing)

    return {
        "clusters_found": len(clusters),
        "clusters_qualifying": len(qualifying),
        "proposals_created": len([c for c in created if "id" in c]),
        "proposals": created,
    }


def op_list_proposals(status: str | None = "pending"):
    proposals = load_jsonl(PROPOSED_FACTS_PATH)
    if status:
        proposals = [p for p in proposals if p.get("status") == status]
    return proposals


def op_decide_proposal(proposal_id: str, decision: str):
    if decision not in ("accept", "skip"):
        raise MemoryError(f"decision must be 'accept' or 'skip', got {decision!r}")

    proposals = load_jsonl(PROPOSED_FACTS_PATH)
    target = None
    for p in proposals:
        if p.get("id") == proposal_id:
            target = p
            break
    if target is None:
        raise MemoryError(f"no proposal with id {proposal_id!r}")
    if target.get("status") != "pending":
        raise MemoryError(f"proposal {proposal_id!r} is already {target.get('status')!r}")

    if decision == "accept":
        facts = load_jsonl(FACTS_PATH)
        facts.append({
            "ts": time.time(),
            "fact": target["proposed_fact"],
            "source_ids": target["source_ids"],
            "source_texts": target["source_texts"],
        })
        write_jsonl(FACTS_PATH, facts)
        target["status"] = "accepted"
    else:
        target["status"] = "skipped"

    write_jsonl(PROPOSED_FACTS_PATH, proposals)
    return target


def op_facts(n: int = 20):
    facts = load_jsonl(FACTS_PATH)
    return facts[-n:] if n > 0 else facts


# ---------------------------------------------------------------------------
# salience-related operations: inspect, pin, prune, archive, revive
# ---------------------------------------------------------------------------

def op_get_entry(entry_id: int):
    conn = get_db()
    row = conn.execute(f"SELECT {ENTRY_COLUMNS} FROM entries WHERE id = ?", (entry_id,)).fetchone()
    archived = False
    if row is None:
        row = conn.execute(f"SELECT {ENTRY_COLUMNS} FROM archived_entries WHERE id = ?", (entry_id,)).fetchone()
        archived = True
    conn.close()

    if row is None:
        raise MemoryError(f"no entry with id {entry_id}")

    (id_, ts, text, tags, model, dim, blob, access_count, last_accessed, pinned,
     provenance, witness, confidence_base, last_confirmed, owner, may_reveal, may_modify, may_delete) = row
    consolidated = entry_id in _consolidated_ids()
    sal = compute_salience(access_count, last_accessed, bool(pinned), consolidated)
    conf = compute_confidence(confidence_base, last_confirmed)

    return {
        "id": id_, "ts": ts, "text": text, "tags": json.loads(tags),
        "archived": archived, "consolidated": consolidated,
        "provenance": provenance, "witness": witness, "owner": owner,
        "permissions": {"may_reveal": bool(may_reveal), "may_modify": bool(may_modify), "may_delete": bool(may_delete)},
        **sal, **conf,
    }


def op_pin(entry_id: int):
    conn = get_db()
    cur = conn.execute("UPDATE entries SET pinned = 1 WHERE id = ?", (entry_id,))
    conn.commit()
    if cur.rowcount == 0:
        is_archived = conn.execute("SELECT 1 FROM archived_entries WHERE id = ?", (entry_id,)).fetchone()
        conn.close()
        if is_archived:
            raise MemoryError(f"entry {entry_id} is archived — revive it first, then pin it")
        raise MemoryError(f"no entry with id {entry_id}")
    conn.close()
    return {"id": entry_id, "pinned": True}


def op_unpin(entry_id: int):
    conn = get_db()
    cur = conn.execute("UPDATE entries SET pinned = 0 WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise MemoryError(f"no active entry with id {entry_id}")
    return {"id": entry_id, "pinned": False}


def op_prune(threshold: float = None, min_age_days: float = None, dry_run: bool = False):
    threshold = PRUNE_DEFAULT_THRESHOLD if threshold is None else threshold
    min_age_days = PRUNE_MIN_AGE_DAYS if min_age_days is None else min_age_days

    conn = get_db()
    rows = conn.execute(f"SELECT {ENTRY_COLUMNS} FROM entries WHERE pinned = 0").fetchall()
    consolidated = _consolidated_ids()
    now = time.time()

    to_archive = []
    for row in rows:
        (id_, ts, text, tags, model, dim, blob, access_count, last_accessed, pinned,
         provenance, witness, confidence_base, last_confirmed, owner, may_reveal, may_modify, may_delete) = row
        age_days = (now - ts) / 86400.0
        if age_days < min_age_days:
            continue
        sal = compute_salience(access_count, last_accessed, False, id_ in consolidated, now)
        if sal["salience"] < threshold:
            to_archive.append({
                "id": id_, "ts": ts, "text": text, "tags": tags, "model": model, "dim": dim,
                "embedding": blob, "access_count": access_count, "last_accessed": last_accessed,
                "provenance": provenance, "witness": witness, "confidence_base": confidence_base,
                "last_confirmed": last_confirmed, "owner": owner, "may_reveal": may_reveal,
                "may_modify": may_modify, "may_delete": may_delete, "salience": sal["salience"],
            })

    if not dry_run:
        for e in to_archive:
            conn.execute(
                "INSERT INTO archived_entries (id, ts, text, tags, model, dim, embedding, access_count, "
                "last_accessed, pinned, provenance, witness, confidence_base, last_confirmed, owner, "
                "may_reveal, may_modify, may_delete, archived_ts, archived_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (e["id"], e["ts"], e["text"], e["tags"], e["model"], e["dim"], e["embedding"],
                 e["access_count"], e["last_accessed"], e["provenance"], e["witness"], e["confidence_base"],
                 e["last_confirmed"], e["owner"], e["may_reveal"], e["may_modify"], e["may_delete"],
                 now, f"salience {e['salience']} < threshold {threshold}"),
            )
            conn.execute("DELETE FROM entries WHERE id = ?", (e["id"],))
        conn.commit()
    conn.close()

    return {
        "dry_run": dry_run, "threshold": threshold, "min_age_days": min_age_days,
        "archived_count": len(to_archive),
        "archived": [{"id": e["id"], "text": e["text"], "salience": e["salience"]} for e in to_archive],
    }


def op_list_archived(n: int = 20):
    if n < 1:
        raise MemoryError("n must be at least 1")
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, ts, text, tags, archived_ts, archived_reason FROM archived_entries "
            "ORDER BY archived_ts DESC LIMIT ?", (n,)
        ).fetchall()
    finally:
        conn.close()
    return [
        {"id": id_, "ts": ts, "text": text, "tags": json.loads(tags),
         "archived_ts": archived_ts, "archived_reason": reason}
        for (id_, ts, text, tags, archived_ts, reason) in rows
    ]


def op_revive(entry_id: int):
    conn = get_db()
    row = conn.execute(f"SELECT {ENTRY_COLUMNS} FROM archived_entries WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        conn.close()
        raise MemoryError(f"no archived entry with id {entry_id}")

    (id_, ts, text, tags, model, dim, blob, access_count, last_accessed, pinned,
     provenance, witness, confidence_base, last_confirmed, owner, may_reveal, may_modify, may_delete) = row
    now = time.time()
    conn.execute(
        "INSERT INTO entries (id, ts, text, tags, model, dim, embedding, access_count, last_accessed, pinned, "
        "provenance, witness, confidence_base, last_confirmed, owner, may_reveal, may_modify, may_delete) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (id_, ts, text, tags, model, dim, blob, access_count + 1, now, pinned,
         provenance, witness, confidence_base, now, owner, may_reveal, may_modify, may_delete),
    )
    conn.execute("DELETE FROM archived_entries WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()
    return {"id": entry_id, "revived": True}


# ---------------------------------------------------------------------------
# Scars — permanent behavioral mutations. Propose -> human decides -> canon.
# ---------------------------------------------------------------------------

def op_propose_scar(trigger_event: str, lesson: str, confidence: float = 0.9,
                     source_ids: list[int] | None = None, supersedes: int | None = None):
    if not (0.0 <= confidence <= 1.0):
        raise MemoryError(f"confidence must be between 0 and 1, got {confidence}")
    ensure_data_dir()
    proposal = {
        "id": uuid.uuid4().hex[:8],
        "proposed_ts": time.time(),
        "trigger_event": trigger_event,
        "lesson": lesson,
        "confidence": confidence,
        "source_ids": source_ids or [],
        "supersedes": supersedes,
        "status": "pending",
    }
    proposals = load_jsonl(PROPOSED_SCARS_PATH)
    proposals.append(proposal)
    write_jsonl(PROPOSED_SCARS_PATH, proposals)
    return proposal


def op_list_scar_proposals(status: str | None = "pending"):
    proposals = load_jsonl(PROPOSED_SCARS_PATH)
    if status:
        proposals = [p for p in proposals if p.get("status") == status]
    return proposals


def op_decide_scar(proposal_id: str, decision: str):
    """Accepting is permanent: the scar goes into scars.jsonl and stays
    there. If it supersedes an earlier scar, that scar is marked
    superseded — not deleted, not edited. Both remain readable; only
    which one is 'canon' right now changes."""
    if decision not in ("accept", "reject"):
        raise MemoryError(f"decision must be 'accept' or 'reject', got {decision!r}")

    proposals = load_jsonl(PROPOSED_SCARS_PATH)
    target = None
    for p in proposals:
        if p.get("id") == proposal_id:
            target = p
            break
    if target is None:
        raise MemoryError(f"no scar proposal with id {proposal_id!r}")
    if target.get("status") != "pending":
        raise MemoryError(f"scar proposal {proposal_id!r} is already {target.get('status')!r}")

    if decision == "accept":
        scars = load_jsonl(SCARS_PATH)

        supersedes = target.get("supersedes")
        if supersedes is not None:
            found = False
            for s in scars:
                if s["id"] == supersedes:
                    if s["status"] != "active":
                        raise MemoryError(f"scar {supersedes} is not active (status={s['status']}), can't supersede it")
                    found = True
                    break
            if not found:
                raise MemoryError(f"no active scar with id {supersedes} to supersede")

        new_scar = {
            "id": (max((s["id"] for s in scars), default=0) + 1),
            "ts": time.time(),
            "trigger_event": target["trigger_event"],
            "lesson": target["lesson"],
            "confidence": target["confidence"],
            "source_ids": target["source_ids"],
            "status": "active",
            "superseded_by": None,
        }
        scars.append(new_scar)

        if supersedes is not None:
            for s in scars:
                if s["id"] == supersedes:
                    s["status"] = "superseded"
                    s["superseded_by"] = new_scar["id"]

        write_jsonl(SCARS_PATH, scars)
        target["status"] = "accepted"
        target["scar_id"] = new_scar["id"]
    else:
        target["status"] = "rejected"

    write_jsonl(PROPOSED_SCARS_PATH, proposals)
    return target


def op_list_scars(status: str | None = "active"):
    scars = load_jsonl(SCARS_PATH)
    if status:
        scars = [s for s in scars if s.get("status") == status]
    return scars


# ---------------------------------------------------------------------------
# Promises — a state machine, not a fact
# ---------------------------------------------------------------------------

def op_add_promise(text: str, owner: str = "system", condition: str | None = None):
    conn = get_db()
    now = time.time()
    conn.execute(
        "INSERT INTO promises (ts_created, text, owner, condition_text, status) VALUES (?, ?, ?, ?, 'pending')",
        (now, text, owner, condition),
    )
    conn.commit()
    promise_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return {"id": promise_id, "text": text, "owner": owner, "condition": condition, "status": "pending"}


def op_list_promises(status: str | None = "pending"):
    conn = get_db()
    if status:
        rows = conn.execute(
            "SELECT id, ts_created, text, owner, condition_text, status, ts_resolved, resolution_note "
            "FROM promises WHERE status = ? ORDER BY ts_created", (status,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, ts_created, text, owner, condition_text, status, ts_resolved, resolution_note "
            "FROM promises ORDER BY ts_created"
        ).fetchall()
    conn.close()
    return [
        {"id": r[0], "ts_created": r[1], "text": r[2], "owner": r[3], "condition": r[4],
         "status": r[5], "ts_resolved": r[6], "resolution_note": r[7]}
        for r in rows
    ]


def op_resolve_promise(promise_id: int, status: str, note: str | None = None):
    if status not in ("fulfilled", "broken", "cancelled"):
        raise MemoryError(f"status must be fulfilled/broken/cancelled, got {status!r}")
    conn = get_db()
    row = conn.execute("SELECT status FROM promises WHERE id = ?", (promise_id,)).fetchone()
    if row is None:
        conn.close()
        raise MemoryError(f"no promise with id {promise_id}")
    if row[0] != "pending":
        conn.close()
        raise MemoryError(f"promise {promise_id} is already {row[0]}")
    now = time.time()
    conn.execute(
        "UPDATE promises SET status = ?, ts_resolved = ?, resolution_note = ? WHERE id = ?",
        (status, now, note, promise_id),
    )
    conn.commit()
    conn.close()
    return {"id": promise_id, "status": status, "resolution_note": note, "ts_resolved": now}


# ---------------------------------------------------------------------------
# Unknowable — stores that something exists, deliberately not what it is
# ---------------------------------------------------------------------------

def op_add_unknowable(description: str, reason: str, confidence_exists: float = 0.8,
                       owner_to_request: str | None = None):
    if not (0.0 <= confidence_exists <= 1.0):
        raise MemoryError(f"confidence_exists must be between 0 and 1, got {confidence_exists}")
    conn = get_db()
    now = time.time()
    conn.execute(
        "INSERT INTO unknowable (ts, description, reason, confidence_exists, owner_to_request, status) "
        "VALUES (?, ?, ?, ?, ?, 'inaccessible')",
        (now, description, reason, confidence_exists, owner_to_request),
    )
    conn.commit()
    uid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return {"id": uid, "description": description, "reason": reason,
            "confidence_exists": confidence_exists, "owner_to_request": owner_to_request, "status": "inaccessible"}


def op_list_unknowable(status: str | None = "inaccessible"):
    conn = get_db()
    if status:
        rows = conn.execute(
            "SELECT id, ts, description, reason, confidence_exists, owner_to_request, status, "
            "resolved_entry_id, resolved_ts FROM unknowable WHERE status = ? ORDER BY ts", (status,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, ts, description, reason, confidence_exists, owner_to_request, status, "
            "resolved_entry_id, resolved_ts FROM unknowable ORDER BY ts"
        ).fetchall()
    conn.close()
    return [
        {"id": r[0], "ts": r[1], "description": r[2], "reason": r[3], "confidence_exists": r[4],
         "owner_to_request": r[5], "status": r[6], "resolved_entry_id": r[7], "resolved_ts": r[8]}
        for r in rows
    ]


def op_resolve_unknowable(unknowable_id: int, resolved_entry_id: int):
    """Something that was opaque became knowable — link it to the real
    content now living in entries/facts, rather than storing content here."""
    conn = get_db()
    row = conn.execute("SELECT status FROM unknowable WHERE id = ?", (unknowable_id,)).fetchone()
    if row is None:
        conn.close()
        raise MemoryError(f"no unknowable with id {unknowable_id}")
    if row[0] != "inaccessible":
        conn.close()
        raise MemoryError(f"unknowable {unknowable_id} is already {row[0]}")
    now = time.time()
    conn.execute(
        "UPDATE unknowable SET status = 'resolved', resolved_entry_id = ?, resolved_ts = ? WHERE id = ?",
        (resolved_entry_id, now, unknowable_id),
    )
    conn.commit()
    conn.close()
    return {"id": unknowable_id, "status": "resolved", "resolved_entry_id": resolved_entry_id}


# ---------------------------------------------------------------------------
# Relations — one edge table: contradictions + everything else
# ---------------------------------------------------------------------------

def op_add_relation(id_a: int, type_a: str, id_b: int, type_b: str, relation_type: str, note: str | None = None):
    if type_a not in VALID_RECORD_TYPES or type_b not in VALID_RECORD_TYPES:
        raise MemoryError(f"type must be one of {sorted(VALID_RECORD_TYPES)}")
    if relation_type not in VALID_RELATION_TYPES:
        raise MemoryError(f"relation_type must be one of {sorted(VALID_RELATION_TYPES)}")

    conn = get_db()
    now = time.time()
    # contradicts/supersedes start unresolved (need a decision later);
    # relates_to/caused_by/supports are just links, resolved from the start.
    status = "unresolved" if relation_type in ("contradicts", "supersedes") else "resolved"
    conn.execute(
        "INSERT INTO relations (ts, id_a, type_a, id_b, type_b, relation_type, note, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (now, id_a, type_a, id_b, type_b, relation_type, note, status),
    )
    conn.commit()
    rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return {"id": rid, "id_a": id_a, "type_a": type_a, "id_b": id_b, "type_b": type_b,
            "relation_type": relation_type, "note": note, "status": status}


def op_list_relations(status: str | None = None, relation_type: str | None = None):
    conn = get_db()
    clauses, params = [], []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if relation_type:
        clauses.append("relation_type = ?")
        params.append(relation_type)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT id, ts, id_a, type_a, id_b, type_b, relation_type, note, status, "
        f"resolved_which, resolution_note, resolved_ts FROM relations {where} ORDER BY ts", params
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "ts": r[1], "id_a": r[2], "type_a": r[3], "id_b": r[4], "type_b": r[5],
         "relation_type": r[6], "note": r[7], "status": r[8], "resolved_which": r[9],
         "resolution_note": r[10], "resolved_ts": r[11]}
        for r in rows
    ]


def op_resolve_relation(relation_id: int, resolved_which: str, note: str | None = None):
    if resolved_which not in ("a", "b", "both_true_different_conditions", "neither"):
        raise MemoryError("resolved_which must be 'a', 'b', 'both_true_different_conditions', or 'neither'")
    conn = get_db()
    row = conn.execute("SELECT status FROM relations WHERE id = ?", (relation_id,)).fetchone()
    if row is None:
        conn.close()
        raise MemoryError(f"no relation with id {relation_id}")
    if row[0] != "unresolved":
        conn.close()
        raise MemoryError(f"relation {relation_id} is already {row[0]}")
    now = time.time()
    conn.execute(
        "UPDATE relations SET status = 'resolved', resolved_which = ?, resolution_note = ?, resolved_ts = ? WHERE id = ?",
        (resolved_which, note, now, relation_id),
    )
    conn.commit()
    conn.close()
    return {"id": relation_id, "status": "resolved", "resolved_which": resolved_which, "resolution_note": note}
