"""Marketing provider primitives — shared by all integration adapters.

Every adapter speaks HTTPS via httpx with short timeouts, maps provider
failures to stable structured error codes (so the Marketing Agent can
reason about them), and NEVER logs or returns credential material.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 20.0

# Structured error codes surfaced to the agent / UI (never raw secrets).
ERR_NOT_CONNECTED = "NOT_CONNECTED"
ERR_INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
ERR_AUTH_EXPIRED = "AUTH_EXPIRED"
ERR_AUTH_REVOKED = "AUTH_REVOKED"
ERR_INSUFFICIENT_PERMISSIONS = "INSUFFICIENT_PERMISSIONS"
ERR_OAUTH_SCOPE_INSUFFICIENT = "OAUTH_SCOPE_INSUFFICIENT"
ERR_GOOGLE_ACCOUNT_NOT_LINKED = "GOOGLE_ACCOUNT_NOT_LINKED_TO_ADS"
ERR_GOOGLE_2SV_REQUIRED = "GOOGLE_2SV_REQUIRED"
ERR_ACCOUNT_NOT_FOUND = "ACCOUNT_NOT_FOUND"
ERR_RATE_LIMITED = "RATE_LIMITED"
ERR_PROVIDER_ERROR = "PROVIDER_ERROR"
ERR_NETWORK_ERROR = "NETWORK_ERROR"
ERR_TIMEOUT = "TIMEOUT"
ERR_MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
ERR_APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
ERR_EXECUTION_DISABLED = "EXECUTION_DISABLED"
ERR_TEST_MODE = "TEST_MODE"
ERR_MISSING_CONFIGURATION = "MISSING_CONFIGURATION"


@dataclass
class ProviderResult:
    """Outcome of one provider operation.

    `executed` is True ONLY when a real external side effect happened.
    `account` carries safe identity (ids/names), never secrets.
    """

    ok: bool
    provider: str
    mode: str = "live"            # live | test
    executed: bool = False
    simulated: bool = False
    error_code: str | None = None
    message: str | None = None
    account: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)
    provider_request_id: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        """Client-safe projection — no credential material, by construction."""
        return {
            "ok": self.ok,
            "provider": self.provider,
            "mode": self.mode,
            "executed": self.executed,
            "simulated": self.simulated,
            "error_code": self.error_code,
            "message": self.message,
            "account": self.account,
            "data": self.data,
            "provider_request_id": self.provider_request_id,
        }


_SECRET_PATTERNS = (
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "client_secret",
    "secret",
    "password",
    "private_key",
    "authorization",
    "bearer",
)


def redact_mapping(mapping: dict[str, Any] | None) -> dict[str, Any]:
    """Return a copy with secret-looking keys replaced by ***REDACTED***."""
    if not mapping:
        return {}
    redacted: dict[str, Any] = {}
    for key, value in mapping.items():
        lowered = str(key).lower()
        if any(p in lowered for p in _SECRET_PATTERNS):
            redacted[key] = "***REDACTED***"
        elif isinstance(value, dict):
            redacted[key] = redact_mapping(value)
        elif isinstance(value, list):
            redacted[key] = [
                redact_mapping(v) if isinstance(v, dict) else v for v in value
            ]
        else:
            redacted[key] = value
    return redacted


def _summarise_httpx_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, httpx.TimeoutException):
        return ERR_TIMEOUT, "The provider did not respond in time. Try again."
    if isinstance(exc, httpx.NetworkError):
        return ERR_NETWORK_ERROR, "Could not reach the provider. Check network connectivity."
    return ERR_PROVIDER_ERROR, f"Provider request failed: {type(exc).__name__}"


def classify_http_status(status: int, provider: str, body_text: str = "") -> tuple[str, str]:
    """Map an HTTP failure to (error_code, safe message). No body echo."""
    if status in (401, 403):
        lowered = body_text.lower()
        if any(s in lowered for s in ("expired", "invalid_grant")):
            return ERR_AUTH_EXPIRED, (
                f"{provider} authorization has expired. Reconnect the account."
            )
        if any(s in lowered for s in ("revoked", "deleted", "disabled")):
            return ERR_AUTH_REVOKED, (
                f"{provider} access was revoked. Reconnect the account."
            )
        if any(s in lowered for s in ("permission", "forbidden", "scope", "authorized")):
            return ERR_INSUFFICIENT_PERMISSIONS, (
                f"Insufficient {provider} permissions. Reconnect with the required scopes."
            )
        return ERR_INVALID_CREDENTIALS, (
            f"{provider} rejected the credentials. Check the key/token and reconnect."
        )
    if status == 404:
        return ERR_ACCOUNT_NOT_FOUND, (
            f"The {provider} account was not found. Verify the account ID."
        )
    if status == 429:
        return ERR_RATE_LIMITED, (
            f"{provider} rate limit hit. Wait before retrying."
        )
    if 500 <= status < 600:
        return ERR_PROVIDER_ERROR, (
            f"{provider} had an internal error (HTTP {status}). Try again later."
        )
    return ERR_PROVIDER_ERROR, f"{provider} request failed (HTTP {status})."


class BaseProvider:
    """Common behaviour for all marketing provider adapters."""

    provider_key: str = "abstract"
    connect_timeout: float = DEFAULT_TIMEOUT_SECONDS

    def _client(self, transport: httpx.BaseTransport | None = None) -> httpx.Client:
        return httpx.Client(timeout=self.connect_timeout, transport=transport)

    @staticmethod
    def _safe_log(extra: dict[str, Any]) -> dict[str, Any]:
        return redact_mapping(extra)

    def now_ms(self) -> int:
        return int(time.time() * 1000)
