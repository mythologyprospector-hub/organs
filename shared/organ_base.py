"""
organ_base.py — the system-wide convention every organ is built on.

This is deliberately small. Its whole job is: no matter which organ you're
talking to, four things are always true —

  1. GET /health   tells you if the organ (and its dependencies) are alive
  2. GET /info     tells you what the organ is and what it can do
  3. Errors always come back as {"error": {"code", "message"}} — never a
     bare stack trace, never a shape that's different organ to organ.
  4. A mutating request (POST/PUT/DELETE) that Critic would classify
     "caution" or "high_risk" is blocked unless it carries proof it went
     through Executive's real approval flow (X-Executive-Approved) or an
     explicit, logged bypass (X-Bypass-Safety) — see the risk gate inside
     _telemetry_middleware below. Before this existed, Critic only ever
     got consulted by callers who chose to ask it (Executive did; nothing
     forced anyone else to). A direct HTTP call to any organ's own risky
     endpoint skipped Critic entirely — found by an external security
     review, closed here so the guarantee holds system-wide, not just
     for callers who remember to route through Executive.

Everything else — the actual endpoints — is organ-specific and lives in
that organ's own main.py. This file never grows opinions about what an
organ *does*, only about how it presents itself to the rest of the system.

Usage (see memory/main.py for a full example):

    from organ_base import create_organ_app, HealthCheck

    app = create_organ_app(
        name="memory",
        version="0.1.0",
        description="Layered memory: ledger, semantic recall, consolidation.",
        capabilities=["add", "recall", "consolidate", "facts"],
        health_checks=[HealthCheck("ollama", check_ollama_fn)],
    )

    @app.get("/memory/recall")
    def recall(...): ...
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
import os
import urllib.error
import urllib.request

from telemetry_client import emit as emit_telemetry
from dataclasses import dataclass, field
from typing import Callable, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

ORGAN_API_VERSION = "1.0"  # the *convention* version, not any one organ's version

from correlation import correlation_headers, set_correlation_id, reset_correlation_id
from organ_client import discover, RegistryError

_logger = logging.getLogger("organ.risk_gate")


@dataclass
class HealthCheck:
    """One dependency an organ wants reported in /health.
    `fn` should return (ok: bool, detail: str) and must not raise —
    organ_base wraps it in a try/except anyway, but keep checks fast and
    side-effect-free (a ping, not a full doctor pass)."""
    name: str
    fn: Callable[[], tuple]


class OrganError(Exception):
    """Raise this anywhere in an organ's endpoint code to get the standard
    error envelope back to the caller, instead of a raw 500."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code


def _ask_critic(caller_organ: str, method: str, path: str, body):
    """Ask the real Critic organ for this exact request's risk tier —
    never re-implements Critic's judgment locally. Returns
    (tier, reasoning). If Critic itself can't be reached, that's not
    the same thing as "this is safe" — it fails closed to high_risk,
    same principle Executive's own Critic integration already uses."""
    try:
        critic_url = discover("critic", timeout=3.0)
        payload = json.dumps({"organ": caller_organ, "method": method, "path": path, "body": body}).encode("utf-8")
        req = urllib.request.Request(
            f"{critic_url}/critic/evaluate", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result.get("risk_tier", "high_risk"), result.get("reasoning", "")
    except (RegistryError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
        return "high_risk", f"critic unreachable — failing closed ({e})"


def create_organ_app(
    name: str,
    version: str,
    description: str,
    capabilities: list[str],
    health_checks: Optional[list[HealthCheck]] = None,
    risk_gate_exempt_paths: Optional[set[str]] = None,
) -> FastAPI:
    """risk_gate_exempt_paths: exact request paths this organ's own
    endpoints should skip the Critic risk gate for entirely — no Critic
    call made at all, not even a "safe" classification. Reserved for
    genuine infrastructure this organ (or the gate mechanism itself)
    depends on to function — e.g. Registry's own /registry/register is
    called by every organ's heartbeat every ~10s; gating it would mean
    no organ could announce itself if Critic were ever briefly
    unreachable at boot, which could cascade into discover() failing
    system-wide. This is NOT a place to exempt something because it's
    inconvenient — every exemption here is a deliberate, load-bearing
    exception, and each one used in this codebase is commented at its
    call site explaining exactly why."""
    health_checks = health_checks or []
    risk_gate_exempt_paths = risk_gate_exempt_paths or set()
    start_time = time.time()

    app = FastAPI(title=f"organ:{name}", version=version)
    app.state.organ_name = name

    @app.exception_handler(OrganError)
    async def _organ_error_handler(request: Request, exc: OrganError):
        response = JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )
        correlation_id = getattr(request.state, "correlation_id", None)
        if correlation_id:
            response.headers["X-Correlation-ID"] = correlation_id
        return response

    @app.exception_handler(Exception)
    async def _unhandled_error_handler(request: Request, exc: Exception):
        # Same envelope even for bugs we didn't anticipate — a caller
        # (another organ) should never have to special-case a raw 500.
        #
        # This handler is invoked by Starlette's ServerErrorMiddleware,
        # which sits OUTSIDE _telemetry_middleware below — not by
        # ExceptionMiddleware, which sits inside it (that's where
        # OrganError above gets handled). By the time an unanticipated
        # exception reaches here, _telemetry_middleware's own `finally:
        # reset_correlation_id(token)` has already run as the exception
        # unwound through it, so the correlation ID's ContextVar is
        # already cleared — get_correlation_id() would return None here.
        # request.state survives that unwind (it's a plain attribute on
        # the same Request object, not a ContextVar), so that's what
        # _telemetry_middleware stashes it in and what this reads back —
        # precisely so a genuine crash still comes back correlatable,
        # which is exactly the response where that matters most.
        response = JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": str(exc)}},
        )
        correlation_id = getattr(request.state, "correlation_id", None)
        if correlation_id:
            response.headers["X-Correlation-ID"] = correlation_id
        return response

    @app.get("/health")
    def health():
        checks = {}
        overall_ok = True
        for hc in health_checks:
            try:
                ok, detail = hc.fn()
            except Exception as e:
                ok, detail = False, f"check raised: {e}"
            checks[hc.name] = {"ok": ok, "detail": detail}
            overall_ok = overall_ok and ok

        return {
            "organ": name,
            "status": "ok" if overall_ok else "degraded",
            "uptime_seconds": round(time.time() - start_time, 1),
            "checks": checks,
        }

    @app.get("/info")
    def info():
        return {
            "organ": name,
            "version": version,
            "organ_api_version": ORGAN_API_VERSION,
            "description": description,
            "capabilities": capabilities,
        }

    @app.middleware("http")
    async def _telemetry_middleware(request: Request, call_next):
        # Health/info are the only unconditional skip: pure discovery/
        # diagnostic surfaces, never organism activity, never risky.
        if request.url.path in {"/health", "/info"}:
            return await call_next(request)

        telemetry_enabled = (
            request.headers.get("X-Telemetry-Internal") != "1"
            and os.environ.get("ORGAN_TELEMETRY_ENABLED", "1") != "0"
            and name != "telemetry"
        )

        correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        token = set_correlation_id(correlation_id)
        # Also stashed on request.state (a plain attribute, not a
        # ContextVar) so the exception handlers above can still read it
        # after this middleware's own `finally` below has already reset
        # the ContextVar — see the long comment on _unhandled_error_handler
        # for why that ordering happens.
        request.state.correlation_id = correlation_id
        started = time.monotonic()

        async def _guarded_call_next(request: Request):
            # The risk gate. Deliberately independent of
            # telemetry_enabled above — whether an organ reports metrics
            # and whether a risky action requires approval are two
            # unrelated concerns. Coupling them here once already meant
            # disabling telemetry (as most test fixtures do, and as a
            # real deployment might for performance) would silently
            # disable the safety gate too — caught before this went
            # anywhere near Bucky, but worth the comment as a reminder
            # not to reintroduce that coupling.
            #
            # GET/HEAD/OPTIONS never touch it — Critic's own rule table
            # already says all GET is "safe", and gating read-only
            # requests would just be needless latency for zero benefit.
            # A request carrying X-Executive-Approved came through
            # Executive's real approval flow already (Executive only
            # sets that header after Critic classified this exact step
            # AND, if required, a human approved it) — re-asking Critic
            # here would be redundant, not more careful. X-Bypass-Safety
            # is a deliberate, visible escape hatch for direct testing —
            # logged, never silent, and it is NOT the default: doing
            # nothing gets you the gate, not the bypass.
            if (
                request.method in ("GET", "HEAD", "OPTIONS")
                or request.url.path in risk_gate_exempt_paths
                # These three organs ARE the approval/routing machinery
                # itself, not performers of risky actions: Critic is the
                # arbiter (can't ask itself for permission to arbitrate);
                # Executive's entire API surface — create/plan/approve/
                # reject/execute_next — already IS the human-approval
                # flow, and it evaluates each step's real risk with
                # Critic internally before ever calling a target organ,
                # so gating Executive's own endpoints too would be
                # circular; IO Interface's /io/handle similarly routes
                # through Critic (then Executive, if required) before
                # ever calling a target organ — it decides where
                # something goes, it doesn't perform the risky action
                # itself. (Path-based exemption doesn't fit these three:
                # Executive's real endpoints carry dynamic {goal_id}/
                # {step_id} segments an exact-match set can't express.)
                or name in ("critic", "executive", "io_interface")
                or request.headers.get("X-Executive-Approved") == "1"
            ):
                return await call_next(request)

            bypass_reason = request.headers.get("X-Bypass-Safety")
            if bypass_reason:
                _logger.warning(
                    f"{name}: risk gate bypassed for {request.method} {request.url.path} "
                    f"— reason given: {bypass_reason!r}"
                )
                return await call_next(request)

            body_bytes = await request.body()
            try:
                body = json.loads(body_bytes) if body_bytes else None
            except json.JSONDecodeError:
                body = None

            tier, reasoning = await asyncio.to_thread(_ask_critic, name, request.method, request.url.path, body)
            if tier in ("caution", "high_risk"):
                return JSONResponse(
                    status_code=403,
                    content={"error": {
                        "code": "requires_approval",
                        "message": (
                            f"this action was classified {tier!r} by Critic ({reasoning}) and "
                            f"requires going through Executive's approval flow. If you're "
                            f"intentionally bypassing this for direct testing, retry with an "
                            f"X-Bypass-Safety header explaining why."
                        ),
                    }},
                )
            return await call_next(request)

        if not telemetry_enabled:
            try:
                return await _guarded_call_next(request)
            finally:
                reset_correlation_id(token)

        try:
            try:
                response = await _guarded_call_next(request)
            except Exception:
                duration_ms = round((time.monotonic() - started) * 1000.0, 3)
                await asyncio.to_thread(
                    emit_telemetry,
                    "failure",
                    name,
                    correlation_id=correlation_id,
                    severity="error",
                    payload={"method": request.method, "path": request.url.path},
                    duration_ms=duration_ms,
                    status="failed",
                )
                raise

            duration_ms = round((time.monotonic() - started) * 1000.0, 3)
            if response.status_code >= 400:
                event_type = "failure"
                status = "failed"
                severity = "error"
            elif request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                event_type = "mutation"
                status = "completed"
                severity = "info"
            else:
                event_type = "request"
                status = "completed"
                severity = "info"

            await asyncio.to_thread(
                emit_telemetry,
                event_type,
                name,
                correlation_id=correlation_id,
                severity=severity,
                payload={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                },
                result={"status_code": response.status_code},
                duration_ms=duration_ms,
                status=status,
            )
            response.headers["X-Correlation-ID"] = correlation_id
            return response
        finally:
            reset_correlation_id(token)

    return app
