"""Shared request-correlation plumbing for the organ HTTP convention.

Kept separate from organ_base/organ_client so the shared HTTP presentation
and discovery clients can both use the same request-scoped correlation ID
without creating an import cycle.
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Optional

_correlation_id: ContextVar[str | None] = ContextVar("organ_correlation_id", default=None)


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def set_correlation_id(value: str) -> Token:
    return _correlation_id.set(value)


def reset_correlation_id(token: Token) -> None:
    _correlation_id.reset(token)


def correlation_headers(headers: Optional[dict] = None) -> dict:
    """Return outbound headers with the current correlation ID preserved.

    Existing caller-supplied headers win; background work with no current
    request remains unchanged.
    """
    result = dict(headers or {})
    correlation_id = get_correlation_id()
    if correlation_id and "X-Correlation-ID" not in result:
        result["X-Correlation-ID"] = correlation_id
    return result
