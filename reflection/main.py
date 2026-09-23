"""
main.py — the Reflection organ.

Run it:
    pip install fastapi uvicorn requests --break-system-packages
    uvicorn main:app --host 127.0.0.1 --port 8004

OFF by default. Enable with:
    curl -X POST localhost:8004/reflection/enable

The background loop checks the toggle fresh every cycle — disabling
takes effect on the next tick, no restart needed.
"""
import asyncio
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))

from organ_base import create_organ_app, HealthCheck, OrganError, correlation_headers  # noqa: E402
from organ_client import attach_to_registry, discover, RegistryError  # noqa: E402
import reflection_core as rc  # noqa: E402

ORGAN_NAME = "reflection"
ORGAN_VERSION = "0.1.0"
SELF_BASE_URL = os.environ.get("REFLECTION_BASE_URL", "http://localhost:8004")

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

CAPABILITIES = ["status", "enable", "disable", "configure", "tick", "history"]

logger = logging.getLogger("organ.reflection")


def _config_check():
    try:
        rc.ensure_files()
        return True, f"state OK at {rc.STATE_PATH}"
    except Exception as e:
        return False, str(e)


app = create_organ_app(
    name=ORGAN_NAME,
    version=ORGAN_VERSION,
    description="Reflection organ: an OFF-BY-DEFAULT background loop that, "
                 "only when enabled, periodically reads recent Memory activity "
                 "and writes a low-confidence, self-authored thought back into "
                 "Memory. Never answers anyone — just notices things.",
    capabilities=CAPABILITIES,
    health_checks=[HealthCheck("state", _config_check)],
)

attach_to_registry(app, name=ORGAN_NAME, base_url=SELF_BASE_URL, version=ORGAN_VERSION, capabilities=CAPABILITIES)


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except rc.ReflectionError as e:
        raise OrganError(code="reflection_error", message=str(e), status_code=400)


# ---------------------------------------------------------------------------
# real implementations of the three injected functions
# ---------------------------------------------------------------------------

def _fetch_context(max_entries: int, max_chars: int) -> str:
    """Pull recent ledger entries from Memory, via its API — same access
    any other organ has, nothing special."""
    try:
        memory_url = discover("memory")
    except RegistryError as e:
        raise RuntimeError(f"memory organ not reachable: {e}")

    req = urllib.request.Request(f"{memory_url}/memory/list?n={max_entries}", headers=correlation_headers())
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            entries = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        raise RuntimeError(f"could not reach memory: {e}")

    lines = [f"- {e.get('text', '')}" for e in entries]
    text = "\n".join(lines)
    return text[-max_chars:] if len(text) > max_chars else text


def _generate_thought(prompt: str, model: str) -> str:
    url = f"{OLLAMA_HOST}/api/generate"
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60.0) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        raise RuntimeError(f"could not reach Ollama at {OLLAMA_HOST}: {e}")
    text = body.get("response")
    if text is None:
        raise RuntimeError(f"Ollama returned no text: {body}")
    return text


def _write_reflection(text: str) -> dict:
    try:
        memory_url = discover("memory")
    except RegistryError as e:
        raise RuntimeError(f"memory organ not reachable: {e}")

    payload = json.dumps({
        "text": text, "tags": ["reflection"], "provenance": "self",
        "witness": "inferred", "confidence": 0.3, "owner": "reflection",
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{memory_url}/memory/add", data=payload,
        headers=correlation_headers({"Content-Type": "application/json"}), method="POST",
    )
    with urllib.request.urlopen(req, timeout=10.0) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _run_tick(force: bool = False):
    state = rc.load_state()
    model = state["model"]
    return rc.op_tick(
        fetch_context=lambda n, c: _fetch_context(n, c),
        generate_thought=lambda prompt: _generate_thought(prompt, model),
        write_reflection=_write_reflection,
        force=force,
    )


# ---------------------------------------------------------------------------
# background loop — runs the blocking tick in a thread so a slow model
# call never freezes this organ's own API while it's "thinking"
# ---------------------------------------------------------------------------

async def _reflection_loop():
    """Polls frequently (every few seconds) so enabling/reconfiguring
    takes effect quickly, but only actually runs a tick once at least
    `interval_seconds` has passed since the last one — the poll rate and
    the tick rate are deliberately different things. Without this split,
    a loop that slept for the full configured interval between checks
    wouldn't notice you'd just enabled it until the NEXT interval had
    already elapsed, which for the 300s default means waiting up to five
    minutes after flipping the toggle before anything happens."""
    last_tick_ts = 0.0
    poll_seconds = 5
    while True:
        state = rc.load_state()
        interval = state.get("interval_seconds", 300)
        now = time.time()
        if state.get("enabled") and (now - last_tick_ts) >= interval:
            try:
                await asyncio.to_thread(_run_tick, False)
            except Exception as e:
                logger.warning(f"reflection tick raised unexpectedly: {e}")
            last_tick_ts = now
        await asyncio.sleep(min(poll_seconds, interval))


@app.on_event("startup")
async def _start_loop():
    asyncio.create_task(_reflection_loop())


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------

class ConfigureRequest(BaseModel):
    interval_seconds: Optional[int] = None
    model: Optional[str] = None
    max_context_entries: Optional[int] = None
    max_context_chars: Optional[int] = None


@app.get("/reflection/status")
def status():
    return _wrap(rc.op_get_status)


@app.post("/reflection/enable")
def enable():
    return _wrap(rc.op_enable)


@app.post("/reflection/disable")
def disable():
    return _wrap(rc.op_disable)


@app.post("/reflection/configure")
def configure(req: ConfigureRequest):
    return _wrap(rc.op_configure, req.interval_seconds, req.model, req.max_context_entries, req.max_context_chars)


@app.post("/reflection/tick")
def tick():
    """Manually trigger one cycle right now, regardless of the toggle —
    for testing. The automatic loop never bypasses the toggle; this
    endpoint deliberately does, since running it by hand is itself the
    explicit permission."""
    return _run_tick(force=True)


@app.get("/reflection/history")
def history(n: int = 20):
    return rc.load_history(n)
