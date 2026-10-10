"""MCP error taxonomy — every failure is classified, never swallowed.

The Marketing Agent reasons about failures, so MCP failures must be
STRUCTURED and HONEST:

  - a provider error never becomes a fake success (no invented data)
  - a rate limit is bounded and reported (no long blocking retry chains)
  - an unconnected integration says so explicitly
  - a write that needs approval says APPROVAL_REQUIRED and does nothing
  - a tenant override attempt is rejected before dispatch

The agent can therefore decide what to do next: record the gap, mark the
tool degraded, and continue with the evidence it actually has.
"""
from __future__ import annotations

import re
from typing import Any

# ── Stable error codes (surfaced to the agent + the UI) ──────────────────

AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
AUTHORIZATION_ERROR = "AUTHORIZATION_ERROR"
RATE_LIMITED = "RATE_LIMITED"
TIMEOUT = "TIMEOUT"
PROVIDER_ERROR = "PROVIDER_ERROR"
VALIDATION_ERROR = "VALIDATION_ERROR"
INTEGRATION_NOT_CONNECTED = "INTEGRATION_NOT_CONNECTED"
APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
EXECUTION_DISABLED = "EXECUTION_DISABLED"
TENANT_SCOPE_ERROR = "TENANT_SCOPE_ERROR"
TOOL_NOT_ALLOWED = "TOOL_NOT_ALLOWED"
CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
INTERNAL_ERROR = "INTERNAL_ERROR"

ERROR_CODES: frozenset[str] = frozenset(
    {
        AUTHENTICATION_ERROR,
        AUTHORIZATION_ERROR,
        RATE_LIMITED,
        TIMEOUT,
        PROVIDER_ERROR,
        VALIDATION_ERROR,
        INTEGRATION_NOT_CONNECTED,
        APPROVAL_REQUIRED,
        EXECUTION_DISABLED,
        TENANT_SCOPE_ERROR,
        TOOL_NOT_ALLOWED,
        CONFIGURATION_ERROR,
        INTERNAL_ERROR,
    }
)

#: "key=value" / "key: value" pairs whose KEY names credential material.
#: Free-text error messages from third-party libraries routinely quote the
#: offending request or config, so the key name is the reliable signal.
_TEXT_SECRET_KV_RE = re.compile(
    r"(?i)\b([a-z0-9_\-]*(?:token|secret|password|passwd|api[_-]?key|"
    r"authorization|credential|client[_-]?secret)[a-z0-9_\-]*)"
    r"(\"?\s*[:=]\s*\"?)([^\s,;)\]}\"']+)"
)

#: Free-floating bearer/basic tokens. Applied FIRST: a KV rule would
#: otherwise consume the word "Bearer" as the value of "Authorization:" and
#: leave the token itself behind.
_TEXT_BEARER_RE = re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._\-+/=]{6,}")

#: Provider key shapes recognisable without their key name: Resend, Google
#: OAuth/API, Google OAuth refresh token, Meta, Stripe and JWTs.
_TEXT_OPAQUE_SECRET_RE = re.compile(
    r"(?<![\w\-])(?:"
    r"re_[A-Za-z0-9]{16,}"
    r"|AIza[0-9A-Za-z_\-]{20,}"
    r"|sk-[A-Za-z0-9_\-]{16,}"
    r"|1//[A-Za-z0-9_\-]{8,}"
    r"|eyJ[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]{4,}"
    r")(?![\w\-])"
)

#: A credential word followed by whitespace (no ``:``/``=``) and then a
#: token-ish blob: "token abc123...", "refresh_token re_...".
_TEXT_BARE_CRED_RE = re.compile(
    r"(?i)\b(?:access[_-]?token|refresh[_-]?token|api[_-]?key|client[_-]?secret|"
    r"secret|password|token)\s+([A-Za-z0-9._\-+/=]{8,})"
)

REDACTED = "***REDACTED***"


def redact_text(text: Any, *, limit: int = 2000) -> str:
    """Scrub credential material out of free text.

    Key-name matching (what ``_redact`` does for structured payloads) cannot
    help a message string, and an untrusted producer — an executor
    interpolating ``str(exc)`` from a third-party library — can put the
    offending input value into that string. So every message leaving the MCP
    layer passes through here, on the same footing as the success path.

    Order matters: bearer first (so "Authorization: Bearer <t>" is consumed
    whole), then recognisable key shapes, then key/value pairs, then a bare
    credential word.
    """
    if text is None:
        return ""
    out = str(text)
    if len(out) > limit:
        out = out[:limit] + "...[truncated]"
    out = _TEXT_BEARER_RE.sub(REDACTED, out)
    out = _TEXT_OPAQUE_SECRET_RE.sub(REDACTED, out)
    out = _TEXT_SECRET_KV_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", out)
    out = _TEXT_BARE_CRED_RE.sub(lambda m: f"{m.group(0).split()[0]} {REDACTED}", out)
    return out


def redact_details(details: dict[str, Any] | None) -> dict[str, Any]:
    """Redact both key names and string values inside an error details map."""
    from backend.app.integrations.marketing.base import _SECRET_PATTERNS

    out: dict[str, Any] = {}
    for key, value in (details or {}).items():
        if any(p in str(key).lower() for p in _SECRET_PATTERNS):
            out[key] = REDACTED
        elif isinstance(value, str):
            out[key] = redact_text(value)
        else:
            out[key] = value
    return out


# Provider structured codes (services/integration_service + integrations/
# marketing/base.py) mapped onto the MCP taxonomy. Unmapped codes fall
# through to PROVIDER_ERROR — never to success.
_PROVIDER_CODE_MAP: dict[str, str] = {
    # authentication / authorization
    "INVALID_CREDENTIALS": AUTHENTICATION_ERROR,
    "AUTH_EXPIRED": AUTHENTICATION_ERROR,
    "AUTH_REVOKED": AUTHENTICATION_ERROR,
    "GOOGLE_ADS_AUTHENTICATION_FAILED": AUTHENTICATION_ERROR,
    "INSUFFICIENT_PERMISSIONS": AUTHORIZATION_ERROR,
    "OAUTH_SCOPE_INSUFFICIENT": AUTHORIZATION_ERROR,
    # connectivity
    "RATE_LIMITED": RATE_LIMITED,
    "TIMEOUT": TIMEOUT,
    "NETWORK_ERROR": PROVIDER_ERROR,
    "PROVIDER_ERROR": PROVIDER_ERROR,
    "MALFORMED_RESPONSE": PROVIDER_ERROR,
    # configuration
    "NOT_CONNECTED": INTEGRATION_NOT_CONNECTED,
    "MISSING_CONFIGURATION": CONFIGURATION_ERROR,
    "ACCOUNT_NOT_FOUND": CONFIGURATION_ERROR,
    "GOOGLE_ADS_ACCOUNT_NOT_LINKED": CONFIGURATION_ERROR,
    "APPROVAL_REQUIRED": APPROVAL_REQUIRED,
    "EXECUTION_DISABLED": EXECUTION_DISABLED,
}


def classify_provider_code(code: str | None) -> str:
    """Map a provider/adapter error code onto the MCP taxonomy.

    Unknown or missing codes become PROVIDER_ERROR. A failure NEVER maps
    to a success code — this is the single conversion point and it is
    deliberately one-directional.
    """
    if not code:
        return PROVIDER_ERROR
    return _PROVIDER_CODE_MAP.get(str(code).upper(), PROVIDER_ERROR)


#: Approved-action executor errors arrive as "<CODE>: <human message>".
#: Mapping the known prefixes preserves the distinction between "not
#: approved" and "the provider refused"; anything unknown is a provider
#: error rather than a silent success.
_EXECUTOR_PREFIX_MAP: dict[str, str] = {
    "INVALID_ACTION_STATE": APPROVAL_REQUIRED,
    "ACTION_ALREADY_EXECUTING": APPROVAL_REQUIRED,
    "ACTION_NOT_FOUND": VALIDATION_ERROR,
    "MERCHANT_ACCESS_DENIED": TENANT_SCOPE_ERROR,
    "EXECUTION_DISABLED_BY_ENVIRONMENT": EXECUTION_DISABLED,
    "GUARDRAIL_REJECTED": APPROVAL_REQUIRED,
    "NOT_CONNECTED": INTEGRATION_NOT_CONNECTED,
    "UNKNOWN_ACTION_TYPE": VALIDATION_ERROR,
    "UNRESOLVABLE_AUDIENCE": VALIDATION_ERROR,
    "INVALID_PAYLOAD": VALIDATION_ERROR,
    "CAMPAIGN_TARGET_EXCEEDS_LIMIT": VALIDATION_ERROR,
    # Provider auth failures must NOT be classified as a retryable provider
    # error: a revoked key fails identically on every attempt, so retrying
    # it would stall the run and then report the wrong reason.
    "INVALID_CREDENTIALS": AUTHENTICATION_ERROR,
    "AUTH_EXPIRED": AUTHENTICATION_ERROR,
    "AUTH_REVOKED": AUTHENTICATION_ERROR,
    "GOOGLE_ADS_AUTHENTICATION_FAILED": AUTHENTICATION_ERROR,
    "INSUFFICIENT_PERMISSIONS": AUTHORIZATION_ERROR,
    "OAUTH_SCOPE_INSUFFICIENT": AUTHORIZATION_ERROR,
    "MISSING_CONFIGURATION": CONFIGURATION_ERROR,
    # Deterministic business-rule refusals: retrying cannot change them.
    "INVALID_DISCOUNT_AMOUNT": VALIDATION_ERROR,
    "DISCOUNT_CANNOT_EXCEED_100_PCT": VALIDATION_ERROR,
    "DISCOUNT_EXCEEDS_MAX_PERCENTAGE": VALIDATION_ERROR,
    "DISCOUNT_EXCEEDS_GUARDRAIL": VALIDATION_ERROR,
    "EXECUTION_ERROR": INTERNAL_ERROR,
}


def classify_executor_error(error: str | None) -> str:
    """Map an ``ExecutorResult.error`` string onto the MCP taxonomy.

    A guardrail rejection arrives as a sentence rather than a code, so it
    is matched explicitly. Getting this right matters beyond reporting: a
    policy refusal must NOT be classified as a retryable provider error, or
    the client would retry a decision that can never change.

    An unmapped code is reported as INTERNAL_ERROR (honest: "we do not know
    what this was") rather than as a retryable PROVIDER_ERROR. The safe
    default for a side-effecting operation is to stop, not to try again.
    """
    if not error:
        return INTERNAL_ERROR
    text = str(error)
    lowered = text.lower()
    if "is not permitted in phase" in lowered or "guardrail" in lowered:
        return APPROVAL_REQUIRED
    code = text.split(":", 1)[0].strip().upper()
    if code in ERROR_CODES:
        return code
    return _EXECUTOR_PREFIX_MAP.get(code, INTERNAL_ERROR)


# ── Retry policy per error class ────────────────────────────────────────

#: Only transient classes are retried, and only a bounded number of times.
RETRYABLE_CODES: frozenset[str] = frozenset({RATE_LIMITED, TIMEOUT, PROVIDER_ERROR})

#: Hard upper bound on any single provider backoff (seconds). Mirrors the
#: LLM provider's MAX_RETRY_DELAY_SECONDS so no retry chain can stall a run.
MAX_RETRY_DELAY_SECONDS = 5.0


class MCPError(Exception):
    """Base class for every MCP-layer failure.

    Carries a stable ``code``, a user-safe ``message`` and optional
    structured ``details``. ``message`` is safe to show the merchant and
    safe to place in the LLM prompt: it is scrubbed by ``redact_text`` on the
    way out (so a producer that interpolated credential material into an
    exception string cannot leak it), it is never a raw provider body, and
    ``details`` values are scrubbed too.
    """

    code: str = INTERNAL_ERROR

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        tool: str | None = None,
        provider: str | None = None,
        details: dict[str, Any] | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.tool = tool
        self.provider = provider
        self.details = details or {}
        self.retry_after = retry_after

    @property
    def safe_message(self) -> str:
        """Credential-scrubbed message — the only form allowed to escape."""
        return redact_text(self.message)

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE_CODES

    def to_dict(self) -> dict[str, Any]:
        """Structured, credential-free error payload for the agent/UI."""
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.safe_message,
            "retryable": self.retryable,
        }
        if self.tool:
            payload["tool"] = self.tool
        if self.provider:
            payload["provider"] = self.provider
        if self.details:
            payload["details"] = redact_details(self.details)
        if self.retry_after is not None:
            payload["retry_after_seconds"] = round(float(self.retry_after), 2)
        return payload

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"{type(self).__name__}({self.code}: {self.message})"


class ToolNotAllowedError(MCPError):
    """The requested tool is not registered / not allowlisted."""

    code = TOOL_NOT_ALLOWED


class ToolValidationError(MCPError):
    """Arguments do not satisfy the tool's declared input schema."""

    code = VALIDATION_ERROR


class TenantScopeError(MCPError):
    """A caller attempted to override the authenticated merchant scope."""

    code = TENANT_SCOPE_ERROR


class IntegrationNotConnectedError(MCPError):
    """The tool needs a live integration this workspace has not connected."""

    code = INTEGRATION_NOT_CONNECTED


class ApprovalRequiredError(MCPError):
    """The tool is a write that cannot run until a human approves it."""

    code = APPROVAL_REQUIRED


class ExecutionDisabledError(MCPError):
    """EXECUTION_ENABLED is off — the write must not happen."""

    code = EXECUTION_DISABLED


class ProviderCallError(MCPError):
    """A provider call failed; ``code`` carries the classified reason."""

    code = PROVIDER_ERROR

    def __init__(
        self,
        message: str,
        *,
        provider_code: str | None = None,
        tool: str | None = None,
        provider: str | None = None,
        details: dict[str, Any] | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(
            message,
            code=classify_provider_code(provider_code),
            tool=tool,
            provider=provider,
            details=details,
            retry_after=retry_after,
        )
        self.provider_code = provider_code


__all__ = [
    "APPROVAL_REQUIRED",
    "AUTHENTICATION_ERROR",
    "AUTHORIZATION_ERROR",
    "ApprovalRequiredError",
    "CONFIGURATION_ERROR",
    "ERROR_CODES",
    "EXECUTION_DISABLED",
    "ExecutionDisabledError",
    "INTEGRATION_NOT_CONNECTED",
    "INTERNAL_ERROR",
    "IntegrationNotConnectedError",
    "MAX_RETRY_DELAY_SECONDS",
    "MCPError",
    "PROVIDER_ERROR",
    "ProviderCallError",
    "RATE_LIMITED",
    "REDACTED",
    "RETRYABLE_CODES",
    "TENANT_SCOPE_ERROR",
    "TIMEOUT",
    "TOOL_NOT_ALLOWED",
    "TenantScopeError",
    "ToolNotAllowedError",
    "ToolValidationError",
    "VALIDATION_ERROR",
    "classify_executor_error",
    "classify_provider_code",
    "redact_details",
    "redact_text",
]