"""
organ_client.py — how any organ finds the registry, registers itself on
startup, and discovers other organs by name instead of by hardcoded port.

organ_base.py defines how an organ *presents itself* (health/info/errors).
This defines how it *finds everyone else*. Together they're the whole
convention — every organ built after Memory should use both.

Usage in an organ's main.py:

    from organ_base import create_organ_app
    from organ_client import attach_to_registry, discover

    app = create_organ_app(name="memory", ...)
    attach_to_registry(app, name="memory", base_url="http://localhost:8001",
                        version="0.1.0", capabilities=[...])

    # later, to call another organ:
    intro_url = discover("introspection")
    requests.get(f"{intro_url}/introspect/machine")

The registry's own address is the one hardcoded thing in the system —
set via ORGAN_REGISTRY_URL, defaults to http://localhost:8000.
"""
import asyncio
import json
import logging
import os
import urllib.error
import urllib.request

from correlation import get_correlation_id

REGISTRY_URL = os.environ.get("ORGAN_REGISTRY_URL", "http://localhost:8000")
HEARTBEAT_INTERVAL = float(os.environ.get("ORGAN_HEARTBEAT_INTERVAL", "10"))


class RegistryError(Exception):
    pass


def _post(path, payload, timeout=5.0, headers=None):
    url = f"{REGISTRY_URL}{path}"
    data = json.dumps(payload).encode("utf-8")
    outbound_headers = dict(headers or {})
    outbound_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=outbound_headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(path, timeout=5.0, headers=None):
    url = f"{REGISTRY_URL}{path}"
    outbound_headers = dict(headers or {})
    correlation_id = get_correlation_id()
    if correlation_id and "X-Correlation-ID" not in outbound_headers:
        outbound_headers["X-Correlation-ID"] = correlation_id
    req = urllib.request.Request(url, headers=outbound_headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def register(name, base_url, version, capabilities):
    """One-shot register/heartbeat call. attach_to_registry() calls this
    on a loop for you — you normally don't need to call it directly.

    Marked internal (same exclusion header discover() already uses) so
    Registry's own telemetry middleware doesn't wrap it. Without this,
    every organ's periodic heartbeat — 12 organs on the default 10s
    interval — generates a telemetry event on every single check-in:
    pure plumbing noise at the same category as /health and /info,
    which are already excluded for exactly this reason, just via a
    path check instead of a header since they're on every organ.
    Registration only happens against Registry specifically, so the
    header (not a hardcoded path in the organ-agnostic organ_base.py)
    is the right mechanism here — same one discover() already uses for
    the same reason."""
    try:
        return _post("/registry/register", {
            "name": name, "base_url": base_url, "version": version, "capabilities": capabilities,
        }, headers={"X-Telemetry-Internal": "1"})
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        raise RegistryError(f"could not reach registry at {REGISTRY_URL}: {e}") from e


def discover(name: str, headers: dict | None = None, timeout: float = 5.0) -> str:
    """Look up another organ's base_url. Raises RegistryError if it's
    unknown OR currently stale (presumed down) — callers shouldn't get
    back an address that's not actually going to answer."""
    try:
        record = _get(f"/registry/organs/{name}", headers=headers, timeout=timeout)
    except urllib.error.HTTPError as e:
        raise RegistryError(f"organ {name!r} not found in registry ({e})") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise RegistryError(f"could not reach registry at {REGISTRY_URL}: {e}") from e

    if record.get("status") != "alive":
        raise RegistryError(f"organ {name!r} is registered but not currently alive (status={record.get('status')})")
    return record["base_url"]


def list_organs(include_stale: bool = True):
    return _get(f"/registry/organs?include_stale={'true' if include_stale else 'false'}")


def attach_to_registry(app, name: str, base_url: str, version: str, capabilities: list[str]):
    """Wire self-registration + a background heartbeat loop into a
    FastAPI app's startup. A registry that's temporarily unreachable at
    boot is logged, not fatal — the organ still comes up and serves
    traffic, and picks up registration on the next heartbeat tick rather
    than refusing to start over a discovery-layer hiccup.

    Two things fixed here that weren't originally: (1) register() is a
    blocking, synchronous urllib call — running it directly inside this
    async loop used to block the whole event loop for however long that
    call took, every ~10s, for the organ's entire lifetime. Wrapped in
    asyncio.to_thread so it runs off-loop like every other blocking call
    in this codebase already does. (2) the loop task was never
    explicitly cancelled on shutdown — an infinite, un-cancelled task
    left scheduled on the loop when a process is asked to exit. The
    shutdown handler below cancels it and waits for that cancellation to
    actually land before FastAPI considers shutdown complete, rather
    than leaving a live task hanging off a process that's trying to
    exit."""
    logger = logging.getLogger(f"organ.{name}")
    heartbeat_task: asyncio.Task | None = None

    async def _heartbeat_loop():
        while True:
            try:
                await asyncio.to_thread(register, name, base_url, version, capabilities)
            except RegistryError as e:
                logger.warning(f"registry check-in failed (will retry): {e}")
            await asyncio.sleep(HEARTBEAT_INTERVAL)

    @app.on_event("startup")
    async def _on_startup():
        nonlocal heartbeat_task
        heartbeat_task = asyncio.create_task(_heartbeat_loop())

    @app.on_event("shutdown")
    async def _on_shutdown():
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
