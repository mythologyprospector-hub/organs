"""
registry_core.py — the organ directory.

An organ counts as "alive" only if it registered or heartbeat-ed within
the last STALE_AFTER_SECONDS. There's no separate "deregister on crash" —
a crashed organ and a cleanly-stopped one look identical to callers: both
just stop checking in, and both age into "stale" the same way. That's
deliberate — you can't rely on a crashing process to tell you it crashed.

Snapshotted to disk so a registry restart doesn't forget who exists —
though every live organ will re-register within one heartbeat interval
anyway, so the snapshot mostly matters for the gap right after restart.
"""
import json
import os
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("REGISTRY_DATA_DIR", str(HERE / "data"))).expanduser()
SNAPSHOT_PATH = DATA_DIR / "organs.json"

STALE_AFTER_SECONDS = float(os.environ.get("REGISTRY_STALE_AFTER", "30"))

_organs: dict = {}


def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_snapshot():
    _ensure_dir()
    if SNAPSHOT_PATH.exists():
        try:
            _organs.update(json.loads(SNAPSHOT_PATH.read_text()))
        except Exception:
            pass  # corrupt/empty snapshot — start clean rather than crash the registry


def _save_snapshot():
    _ensure_dir()
    SNAPSHOT_PATH.write_text(json.dumps(_organs, indent=2))


_load_snapshot()


def _with_status(record):
    age = time.time() - record["last_heartbeat"]
    status = "alive" if age <= STALE_AFTER_SECONDS else "stale"
    return {**record, "status": status, "last_heartbeat_age_seconds": round(age, 1)}


def register(name, base_url, version, capabilities):
    """Upsert. Also serves as the heartbeat — an organ just calls this
    again on its interval rather than there being a separate endpoint."""
    now = time.time()
    existing = _organs.get(name)
    record = {
        "name": name,
        "base_url": base_url,
        "version": version,
        "capabilities": capabilities,
        "first_registered": existing["first_registered"] if existing else now,
        "last_heartbeat": now,
    }
    _organs[name] = record
    _save_snapshot()
    return _with_status(record)


def deregister(name):
    if name in _organs:
        del _organs[name]
        _save_snapshot()
        return True
    return False


def get(name):
    record = _organs.get(name)
    return _with_status(record) if record else None


def list_all(include_stale=True):
    out = [_with_status(r) for r in _organs.values()]
    if not include_stale:
        out = [o for o in out if o["status"] == "alive"]
    out.sort(key=lambda o: o["name"])
    return out
