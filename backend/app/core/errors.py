"""
Structured error helpers.

Centralised error responses ensure:
  - Consistent JSON shape across all endpoints
  - No stack traces, secrets, or internal details exposed to clients
  - All errors are logged with enough context for debugging
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)


def safe_error(status_code: int, detail: str) -> HTTPException:
    """
    Return an HTTPException whose detail is safe to expose to clients.

    Never include: API keys, stack traces, raw DB errors, internal paths.
    """
    return HTTPException(status_code=status_code, detail=detail)


def ai_unavailable() -> HTTPException:
    return safe_error(503, "AI provider not configured. Set LLM_API_KEY in environment.")


def merchant_not_found(merchant_id: Any) -> HTTPException:
    return safe_error(404, f"Merchant not found: {merchant_id}")


def ingestion_failed(reason: str) -> HTTPException:
    return safe_error(500, f"Knowledge ingestion failed: {reason}")


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all exception handler.

    Logs the full exception for debugging, returns a safe generic message
    to the client — never leaks stack traces or secrets.
    """
    log.exception("Unhandled exception on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred. Please try again later."},
    )
