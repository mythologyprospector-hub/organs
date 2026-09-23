"""
telemetry_client.py — the shared client convention for operational telemetry.

Every organ can emit observation events without knowing Telemetry's address.
Discovery always goes through the Registry. Telemetry is deliberately
best-effort: an organ operation that already succeeded must not become a
failure merely because the observation organ is unavailable.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from organ_client import discover, RegistryError

LOGGER = logging.getLogger("organs.telemetry")


def emit(
    event_type: str,
    source: str,
    *,
    actor: str | None = None,
    correlation_id: str | None = None,
    parent_event_id: str | None = None,
    severity: str = "info",
    payload: dict | None = None,
    result: dict | None = None,
    duration_ms: float | None = None,
    status: str = "completed",
    provenance: dict | None = None,
    timeout: float = 1.0,
) -> bool:
    """Emit one telemetry event. Return False when Telemetry is unavailable
    OR when the event itself can't be serialized — either way, this must
    never raise. The module docstring's promise ("an organ operation that
    already succeeded must not become a failure merely because the
    observation organ is unavailable") covers unavailability; a bad
    payload is a different failure mode but the same guarantee applies —
    currently the only caller (organ_base.py's own middleware) always
    passes plain str/int payloads, so this can't fire today, but this
    function is documented as directly callable by any organ, and the
    first organ that ever emits something non-JSON-serializable
    shouldn't turn its own successful operation into a 500."""
    try:
        telemetry_url = discover("telemetry", headers={"X-Telemetry-Internal": "1"}, timeout=timeout)
        body = {
            "event_type": event_type,
            "source": source,
            "actor": actor,
            "correlation_id": correlation_id,
            "parent_event_id": parent_event_id,
            "severity": severity,
            "payload": payload,
            "result": result,
            "duration_ms": duration_ms,
            "status": status,
            "provenance": provenance,
        }
        encoded = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{telemetry_url}/telemetry/events",
            data=encoded,
            headers={"Content-Type": "application/json", "X-Telemetry-Internal": "1"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except (RegistryError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        LOGGER.debug("telemetry unavailable; event not recorded: %s", exc)
        return False
    except (TypeError, ValueError) as exc:
        # json.dumps failing on the event body — not a network/availability
        # problem, but the same "must not break the caller" guarantee applies.
        LOGGER.warning("telemetry event could not be serialized; not recorded: %s", exc)
        return False
