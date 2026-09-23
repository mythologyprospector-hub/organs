"""
tui_data.py — the data layer for the Organs TUI. Every function here
makes a real HTTP call to a real organ (discovered through the real
Registry, same as any organ discovering another) and returns a plain
dict/list, or a clean {"error": "..."} on failure — NEVER raises, same
discipline every organ's own health checks already hold themselves to.
A dashboard panel that crashes the whole terminal because one organ was
restarting defeats the entire point of a live status view.

Deliberately split from organs_tui.py's curses rendering loop, for the
same reason every organ splits `<organ>_core.py` from `main.py`: curses
itself isn't meaningfully unit-testable (it needs a real terminal), but
every real HTTP call and its real failure handling is — so that's
exactly where the boundary falls. This file has no curses import in it
at all.

This is also the first thing in the whole system that only CONSUMES —
every organ built before this one provides a capability something else
calls; the TUI calls all of them and provides nothing back. It doesn't
register with the Registry for that reason: nothing needs to discover
a terminal window.
"""
import json
import os
import urllib.error
import urllib.request

REGISTRY_URL = os.environ.get("ORGAN_REGISTRY_URL", "http://localhost:8000")
REQUEST_TIMEOUT = float(os.environ.get("TUI_REQUEST_TIMEOUT", "3.0"))
# /io/handle can synchronously call Critic, the target organ, and
# sometimes Executive (creating a gated goal) — a real chain of real
# HTTP calls, not one round-trip. Give it real room, separate from the
# snappy 3s budget every read-only dashboard panel uses.
IO_REQUEST_TIMEOUT = float(os.environ.get("TUI_IO_TIMEOUT", "30.0"))


def _get(url: str, timeout: float = None):
    """Real GET, JSON in, JSON out. Never raises — {"error": "..."}
    instead, so a panel can render that string and every OTHER panel
    keeps refreshing on its own schedule regardless."""
    try:
        with urllib.request.urlopen(url, timeout=timeout or REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


def _post(url: str, body: dict, timeout: float = None):
    """Real POST, JSON in, JSON out. Never raises. An HTTPError (e.g. a
    400 from a malformed request) still carries the target organ's own
    structured error envelope in its body — surface that instead of
    just the HTTP status, same instinct as Forge's _run_sandbox_call."""
    try:
        payload = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout or REQUEST_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"error": f"{e} — {raw}"}
    except Exception as e:
        return {"error": str(e)}


def fetch_registry(registry_url: str = None):
    result = _get(f"{registry_url or REGISTRY_URL}/registry/organs")
    if isinstance(result, dict) and "error" in result:
        return result
    return {"organs": result}


def _base_urls(registry_snapshot: dict) -> dict:
    return {
        o["name"]: o["base_url"]
        for o in registry_snapshot.get("organs", [])
        if isinstance(o, dict) and "name" in o and "base_url" in o
    }


def _fetch_from(base_urls: dict, organ_name: str, path: str):
    base_url = base_urls.get(organ_name)
    if not base_url:
        return {"error": f"{organ_name!r} not currently registered"}
    return _get(f"{base_url}{path}")


def base_urls_from_registry(registry_snapshot: dict) -> dict:
    """Public wrapper — the Input panel needs to look up io_interface's
    base_url on-demand at submit time, not just inside fetch_all's
    periodic snapshot."""
    return _base_urls(registry_snapshot)


def send_io_interpret(base_url: str, text: str):
    """Dry run — shows what WOULD happen without doing it or creating a
    goal. No gating needed to call this one: it can't act on anything."""
    if not base_url:
        return {"error": "io_interface not currently registered"}
    return _post(f"{base_url}/io/interpret", {"text": text}, timeout=IO_REQUEST_TIMEOUT)


def send_io_handle(base_url: str, text: str):
    """The real thing — routes through the real Critic, and anything
    flagged becomes a real Executive goal instead of running, same gate
    every other caller of /io/handle goes through. A human typing this
    directly into a live terminal IS the human-in-the-loop step; this
    function adds no gating logic of its own on top of what io_interface
    already does, on purpose — reimplementing that here would be
    exactly the kind of second opinion CONTRIBUTING.md's reuse rule
    warns against."""
    if not base_url:
        return {"error": "io_interface not currently registered"}
    return _post(f"{base_url}/io/handle", {"text": text}, timeout=IO_REQUEST_TIMEOUT)


def send_executive_approve(base_url: str, goal_id: str, step_id: str, approved_by: str = "tui"):
    """Real POST to the real Executive organ — the same
    /executive/goals/{goal_id}/steps/{step_id}/approve a curl call would
    hit. This function adds no gating logic of its own; the confirmation
    prompt lives in organs_tui.py's own keybinding handling, one layer
    up, the same way /io/handle's gating lives in io_interface itself
    rather than here."""
    if not base_url:
        return {"error": "executive not currently registered"}
    return _post(f"{base_url}/executive/goals/{goal_id}/steps/{step_id}/approve", {"approved_by": approved_by})


def send_executive_reject(base_url: str, goal_id: str, step_id: str, reason: str = ""):
    if not base_url:
        return {"error": "executive not currently registered"}
    return _post(f"{base_url}/executive/goals/{goal_id}/steps/{step_id}/reject", {"reason": reason})


def send_executive_execute_next(base_url: str, goal_id: str):
    """Runs exactly one already-approved step — the actual call to the
    target organ (Forge, Orchestrator, whatever the step names), not
    just a status flip like approve/reject are. Same
    /executive/goals/{goal_id}/execute_next a curl call would hit;
    Executive itself decides whether there's anything left to run and
    what 'done' means, not this function."""
    if not base_url:
        return {"error": "executive not currently registered"}
    return _post(f"{base_url}/executive/goals/{goal_id}/execute_next", {})


def fetch_all(registry_url: str = None) -> dict:
    """One real snapshot of the whole system. Registry unreachable
    means every OTHER fetch below gets no base_url and returns its own
    clean 'not currently registered' error — the dashboard degrades to
    'nothing is discoverable right now' rather than crashing outright."""
    registry = fetch_registry(registry_url)
    base_urls = _base_urls(registry) if "error" not in registry else {}

    return {
        "registry": registry,
        "memory": _fetch_from(base_urls, "memory", "/memory/stats"),
        "introspection": _fetch_from(base_urls, "introspection", "/introspect/summary"),
        "forge_jobs": _fetch_from(base_urls, "forge", "/forge/jobs"),
        "telemetry_stats": _fetch_from(base_urls, "telemetry", "/telemetry/stats"),
        "telemetry_recent": _fetch_from(base_urls, "telemetry", "/telemetry/recent?limit=15"),
        "executive_goals": _fetch_from(base_urls, "executive", "/executive/goals"),
        "orchestrator_services": _fetch_from(base_urls, "orchestrator", "/orchestrator/services"),
        "reflection_status": _fetch_from(base_urls, "reflection", "/reflection/status"),
        "sandbox_doctor": _fetch_from(base_urls, "sandbox", "/sandbox/doctor"),
        "bus_topics": _fetch_from(base_urls, "communications", "/bus/topics"),
        "critic_rules": _fetch_from(base_urls, "critic", "/critic/rules"),
    }


def fetch_live_checks(registry_snapshot: dict) -> list[dict]:
    """Run a read-only operational sweep against the endpoints that already
    exist in the installed organs. This is not a substitute for the test
    suites; it answers a different question: are the live HTTP surfaces and
    their key diagnostics reachable right now?

    Every check is a real GET discovered through the Registry. No endpoint
    here mutates system state.
    """
    base_urls = _base_urls(registry_snapshot) if not is_error(registry_snapshot) else {}
    checks = [
        ("registry", None, "/registry/organs"),
        ("memory", "health", "/health"),
        ("communications", "doctor", "/bus/doctor"),
        ("orchestrator", "doctor", "/orchestrator/doctor"),
        ("reflection", "status", "/reflection/status"),
        ("introspection", "summary", "/introspect/summary"),
        ("sandbox", "doctor", "/sandbox/doctor"),
        ("critic", "rules", "/critic/rules"),
        ("executive", "goals", "/executive/goals"),
        ("io_interface", "catalog", "/io/catalog"),
        ("forge", "jobs", "/forge/jobs"),
        ("telemetry", "stats", "/telemetry/stats"),
    ]
    out = []
    for organ, label, path in checks:
        if organ == "registry":
            result = registry_snapshot
        else:
            result = _fetch_from(base_urls, organ, path)
        out.append({"organ": organ, "label": label or "organs", "ok": not is_error(result), "result": result})
    return out


def format_age(seconds) -> str:
    """Human-friendly relative time — used everywhere a panel shows
    'last heartbeat' or 'created'. Pure function, no I/O, easy to test
    at every boundary without a fake server."""
    if seconds is None:
        return "unknown"
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "unknown"
    if seconds < 0:
        return "just now"
    if seconds < 60:
        return f"{seconds:.0f}s ago"
    if seconds < 3600:
        return f"{seconds / 60:.0f}m ago"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h ago"
    return f"{seconds / 86400:.1f}d ago"


def is_error(value) -> bool:
    return isinstance(value, dict) and "error" in value and len(value) == 1
