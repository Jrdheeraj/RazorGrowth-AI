"""MCP client â€” the single invocation path for every Marketing Agent tool.

Responsibilities, in order, for one ``call``:

  1. resolve the name against the allowlisted registry (unknown â‡’ refused)
  2. sanitize arguments (tenant/credential/guardrail keys stripped)
  3. validate arguments against the tool's input schema
  4. enforce policy (tenant â†’ integration â†’ approval â†’ execution)
  5. serve from the per-run cache when the tool is read-only and the exact
     query was already answered this run
  6. invoke with bounded retries that honour a provider Retry-After hint
  7. normalize the result (redacted, summarized, structured) and record a
     safe observability entry

MCP is NOT the agent: this module never plans, never approves, and never
invents a result. A provider failure is returned and recorded as a failure.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from backend.app.integrations.mcp.context import MCPExecutionContext
from backend.app.integrations.mcp.errors import (
    APPROVAL_REQUIRED,
    EXECUTION_DISABLED,
    INTERNAL_ERROR,
    MAX_RETRY_DELAY_SECONDS,
    MCPError,
    ProviderCallError,
    REDACTED,
    VALIDATION_ERROR,
    redact_text,
)
from backend.app.integrations.mcp.registry import get_mcp_registry
from backend.app.integrations.mcp.schemas import MCPToolSpec
from backend.app.integrations.mcp.transport import InProcessTransport, MCPTransport
from backend.app.integrations.mcp.validation import (
    sanitize_arguments,
    validate_arguments,
    validate_output,
)

log = logging.getLogger(__name__)

#: Bounded retry budget for transient provider failures.
DEFAULT_MAX_RETRIES = 2

#: Never hand the model an unbounded provider payload. Long lists are
#: summarized (count + head) rather than truncated silently, so the agent
#: knows there is more without the prompt exploding.
MAX_LIST_ITEMS_FOR_LLM = 25
MAX_STRING_CHARS_FOR_LLM = 2000


@dataclass
class MCPToolCallRecord:
    """One safe observability row for a single MCP invocation."""

    tool: str
    server: str
    provider: str
    status: str                      # success | error | denied
    read_only: bool
    requires_approval: bool
    risk_level: str
    duration_ms: int = 0
    error_code: str | None = None
    error_message: str | None = None
    cached: bool = False
    retries: int = 0
    summary: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    # â”€â”€ observability context (no secrets, no payloads) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    run_id: str | None = None
    domain: str | None = None
    started_at: str | None = None
    #: Approval state of THIS invocation: not_applicable (reads/local
    #: writes) | required (withheld for a human) | withheld (execution
    #: switch off) | approved (human-approved action executed).
    approval_state: str = "not_applicable"
    #: Stamped by the agent's observability mirror (client-side the run
    #: phase is unknown): agent phase + AI-Team analysis cycle id.
    phase: str | None = None
    analysis_cycle_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Tenant-safe projection for state, events and the dashboard.

        Contains no arguments values from forbidden keys, no prompts, no
        provider bodies and no credentials by construction.
        """
        return {
            "tool": self.tool,
            "server": self.server,
            "domain": self.domain,
            "provider": self.provider,
            "status": self.status,
            "read_only": self.read_only,
            "requires_approval": self.requires_approval,
            "risk_level": self.risk_level,
            "duration_ms": self.duration_ms,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "cached": self.cached,
            "retries": self.retries,
            "summary": self.summary,
            "args": self.arguments,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "approval_state": self.approval_state,
            "phase": self.phase,
            "analysis_cycle_id": self.analysis_cycle_id,
        }


# â”€â”€ result normalization â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _truncate(value: Any, *, _depth: int = 0) -> Any:
    """Bound a payload for the LLM without hiding that data was truncated."""
    if _depth > 6:
        return "<nested-too-deep>"
    if isinstance(value, str):
        if len(value) > MAX_STRING_CHARS_FOR_LLM:
            return value[:MAX_STRING_CHARS_FOR_LLM] + f"...[+{len(value) - MAX_STRING_CHARS_FOR_LLM} chars]"
        return value
    if isinstance(value, dict):
        return {k: _truncate(v, _depth=_depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        if len(value) > MAX_LIST_ITEMS_FOR_LLM:
            head = [_truncate(v, _depth=_depth + 1) for v in value[:MAX_LIST_ITEMS_FOR_LLM]]
            return {
                "_truncated": True,
                "total_items": len(value),
                "shown_items": len(head),
                "items": head,
            }
        return [_truncate(v, _depth=_depth + 1) for v in value]
    return value


def _redact(value: Any, *, _depth: int = 0, _seen: set[int] | None = None) -> Any:
    """Drop anything that looks like credential material, by key name.

    Mirrors integrations/marketing/base.redact_mapping but recurses into
    list/scalar positions too, so a secret cannot hide inside a list.

    Depth-bounded and cycle-guarded for the same reason ``_truncate`` is:
    redaction runs on provider payloads that may be arbitrarily nested or
    self-referential, and a RecursionError here would abort a call with a
    confusing error instead of an honest classified failure.

    Deliberately KEY-NAME based only. Structured payloads come from the
    platform's own providers, which keep secrets in secret-named fields, so
    name matching is both sufficient and predictable. The aggressive
    free-text scrubber (``errors.redact_text``) is applied on the ERROR path
    instead, where an untrusted producer can interpolate an exception string
    that quotes its own input — and keeping it off the success path means a
    campaign subject line containing the word "token" is not mangled.
    """
    from backend.app.integrations.marketing.base import _SECRET_PATTERNS

    if _depth > 8:
        return "<nested-too-deep>"
    if isinstance(value, (dict, list)):
        seen = _seen if _seen is not None else set()
        marker = id(value)
        if marker in seen:
            return "<cyclic>"
        seen.add(marker)
        try:
            if isinstance(value, dict):
                out: dict[str, Any] = {}
                for k, v in value.items():
                    if any(p in str(k).lower() for p in _SECRET_PATTERNS):
                        out[k] = REDACTED
                    else:
                        out[k] = _redact(v, _depth=_depth + 1, _seen=seen)
                return out
            return [
                _redact(v, _depth=_depth + 1, _seen=seen) for v in value
            ]
        finally:
            seen.discard(marker)
    return value


def normalize_result(spec: MCPToolSpec, raw: dict[str, Any]) -> dict[str, Any]:
    """Build the normalized envelope the agent and the UI consume."""
    return {
        "tool": spec.name,
        "status": "success",
        # Bound first (cheap, and it caps what redaction must walk), then
        # scrub. Scrubbing last means a secret is never returned to the
        # model even inside a payload that would otherwise be truncated.
        "data": _redact(_truncate(raw)),
        "metadata": {
            "provider": spec.provider,
            "server": spec.server,
            "read_only": spec.read_only,
            "tenant_scoped": True,
            "requires_approval": spec.requires_approval,
            "risk_level": spec.risk_level,
        },
    }


def normalize_error(spec: MCPToolSpec, exc: MCPError) -> dict[str, Any]:
    """Build the normalized failure envelope.

    The status is honest â€” never 'success' â€” and carries the classified
    error code plus a safe message the agent can reason about.
    """
    return {
        "tool": spec.name,
        "status": "error",
        "data": None,
        "error": exc.to_dict(),
        "metadata": {
            "provider": spec.provider,
            "server": spec.server,
            "read_only": spec.read_only,
            "tenant_scoped": True,
            "requires_approval": spec.requires_approval,
            "risk_level": spec.risk_level,
        },
    }


def summarize(spec: MCPToolSpec, result: dict[str, Any]) -> str:
    """One honest line for the activity feed â€” never a fabricated claim."""
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, dict):
        return "done"
    if data.get("connected") is False or data.get("status") in {
        "requires_integration",
        "error",
    }:
        return data.get("note") or str(data.get("status") or "unavailable")
    for key in ("recoverable_value_inr", "total_revenue_inr", "campaign_count"):
        if key in data:
            value = data[key]
            if isinstance(value, (int, float)):
                return f"{key}={value}"
    for key in ("failed_payment_count", "audience_count", "customer_count", "total"):
        if isinstance(data.get(key), int):
            return f"{key}={data[key]}"
    if isinstance(data.get("segments"), list):
        return f"{len(data['segments'])} segments"
    if isinstance(data.get("campaigns"), list):
        return f"{len(data['campaigns'])} campaigns"
    if isinstance(data.get("items"), list):
        return f"{len(data['items'])} items"
    return "done"


class MCPClient:
    """Standardized tool connectivity for the Marketing Agent."""

    def __init__(
        self,
        ctx: MCPExecutionContext,
        *,
        max_retries: int = DEFAULT_MAX_RETRIES,
        sleep: Callable[[float], None] = time.sleep,
        on_call: Callable[[MCPToolCallRecord], None] | None = None,
        transport: MCPTransport | None = None,
    ) -> None:
        self._ctx = ctx
        self._registry = get_mcp_registry()
        self._max_retries = max(0, int(max_retries))
        self._sleep = sleep
        self._on_call = on_call
        # Transport seam: in-process today, Streamable HTTP later â€” the
        # client never imports a provider implementation directly.
        self._transport: MCPTransport = transport or InProcessTransport()
        self.records: list[MCPToolCallRecord] = []

    @property
    def context(self) -> MCPExecutionContext:
        return self._ctx

    @property
    def max_retries(self) -> int:
        return self._max_retries

    @property
    def sleep(self) -> Callable[[float], None]:
        return self._sleep

    @property
    def transport(self) -> MCPTransport:
        return self._transport

    # â”€â”€ metrics â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def metrics(self) -> dict[str, Any]:
        """Run-level MCP performance counters (no secrets, no payloads)."""
        cache_hits = sum(1 for r in self.records if r.cached)
        return {
            "mcp_calls": len(self.records),
            "mcp_cache_hits": cache_hits,
            "mcp_cache_misses": len(self.records) - cache_hits,
            "mcp_retries": sum(r.retries for r in self.records),
            "mcp_errors": sum(1 for r in self.records if r.status != "success"),
            "mcp_rate_limited": sum(
                1 for r in self.records if r.error_code == "RATE_LIMITED"
            ),
            "mcp_total_ms": sum(r.duration_ms for r in self.records),
            "degraded_providers": sorted(self._ctx.degraded_providers),
        }

    def clear_run_state(self) -> None:
        """Reset per-run caches (called at the start of every agent run)."""
        self._ctx.cache.clear()
        self._ctx.degraded_providers.clear()
        self.records.clear()

    # â”€â”€ discovery â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def catalog(self, *, phase: str | None = None, include_write: bool = True) -> list[dict[str, Any]]:
        """Phase-scoped, connection-aware tool catalog for LLM prompts."""
        from backend.app.services import integration_service as svc

        connected = {
            p
            for p in ("resend", "google_ads", "meta_ads", "instagram")
            if svc.connected_row(self._ctx.db, self._ctx.merchant_id, p) is not None
        }
        return self._registry.catalog(
            phase=phase,
            include_write=include_write,
            only_providers=connected,
        )

    def catalog_for_agent(
        self,
        agent: str,
        *,
        phase: str | None = None,
        include_write: bool = True,
        stage_tools: Any = None,
    ) -> list[dict[str, Any]]:
        """Discovery for ONE agent: its granted domains + live connections.

        This is the whole cost of onboarding a new agent (Marketing, Product,
        Growth Radar): construct an ``MCPClient`` for the authenticated
        merchant, ask for its catalog, and call tools. There is no per-agent
        client, registry, policy or cache.

        ``stage_tools`` optionally narrows further to the names the agent
        legitimately needs at the current stage, so a multi-stage agent keeps
        each prompt minimal instead of shipping its whole grant to every call.
        """
        from backend.app.services import integration_service as svc

        connected = {
            p
            for p in ("resend", "google_ads", "meta_ads", "instagram")
            if svc.connected_row(self._ctx.db, self._ctx.merchant_id, p) is not None
        }
        return self._registry.catalog(
            phase=phase,
            include_write=include_write,
            only_providers=connected,
            domains=_agent_domains(agent),
            stage_tools=stage_tools,
        )

    # â”€â”€ invocation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def call(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        approved_action_id: Any = None,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Invoke one allowlisted MCP tool.

        Always returns a normalized envelope (``status`` is honest). Never
        raises for a provider or policy failure â€” the agent reasons about
        the structured error instead of crashing. Programming errors in the
        handler surface as INTERNAL_ERROR rather than a fake success.
        """
        from backend.app.integrations.mcp import policy as policy_mod

        started = time.perf_counter()
        started_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        try:
            spec = self._registry.spec(name)  # unknown â‡’ TOOL_NOT_ALLOWED
        except MCPError as exc:
            self._record(
                MCPToolCallRecord(
                    tool=str(name),
                    server="unknown",
                    provider="unknown",
                    status="denied",
                    read_only=False,
                    requires_approval=False,
                    risk_level="critical",
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    error_code=exc.code,
                    error_message=exc.safe_message,
                    summary="tool refused â€” not registered",
                    run_id=self._ctx.run_id,
                    started_at=started_at,
                    approval_state="not_applicable",
                )
            )
            return {
                "tool": str(name),
                "status": "error",
                "data": None,
                "error": exc.to_dict(),
                "metadata": {"tenant_scoped": True},
            }

        try:
            clean, dropped = sanitize_arguments(spec, arguments)
            validated = validate_arguments(spec, clean)
            action_uuid = _as_uuid(approved_action_id)
            policy_mod.enforce(self._ctx, spec, approved_action_id=action_uuid)
        except MCPError as exc:
            rec = MCPToolCallRecord(
                tool=spec.name,
                server=spec.server,
                provider=spec.provider,
                status="denied",
                read_only=spec.read_only,
                requires_approval=spec.requires_approval,
                risk_level=spec.risk_level,
                duration_ms=int((time.perf_counter() - started) * 1000),
                error_code=exc.code,
                error_message=exc.safe_message,
                summary=f"refused â€” {exc.code}",
                arguments={"dropped": dropped} if dropped else {},
                run_id=self._ctx.run_id,
                domain=spec.domain,
                started_at=started_at,
                approval_state=_approval_state(spec, "denied", exc.code),
            )
            self._record(rec)
            envelope = normalize_error(spec, exc)
            if dropped:
                envelope["metadata"]["dropped_arguments"] = dropped
            return envelope

        cache_key = self._ctx.cache_key(spec.name, validated)
        if spec.read_only and use_cache and cache_key in self._ctx.cache:
            cached = self._ctx.cache[cache_key]
            envelope = normalize_result(spec, cached)
            envelope["metadata"]["cache_hit"] = True
            self._record(
                MCPToolCallRecord(
                    tool=spec.name,
                    server=spec.server,
                    provider=spec.provider,
                    status="success",
                    read_only=True,
                    requires_approval=spec.requires_approval,
                    risk_level=spec.risk_level,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    cached=True,
                    summary="cached",
                    arguments=_safe_args(validated),
                    run_id=self._ctx.run_id,
                    domain=spec.domain,
                    started_at=started_at,
                    approval_state="not_applicable",
                )
            )
            return envelope

        raw, retries, exc = self._invoke_with_retries(spec, validated, action_uuid)
        duration = int((time.perf_counter() - started) * 1000)

        if exc is not None:
            self._ctx.mark_degraded(spec.provider)
            self._record(
                MCPToolCallRecord(
                    tool=spec.name,
                    server=spec.server,
                    provider=spec.provider,
                    status="error",
                    read_only=spec.read_only,
                    requires_approval=spec.requires_approval,
                    risk_level=spec.risk_level,
                    duration_ms=duration,
                    error_code=exc.code,
                    error_message=exc.safe_message,
                    retries=retries,
                    summary=f"failed â€” {exc.code}",
                    arguments=_safe_args(validated),
                    run_id=self._ctx.run_id,
                    domain=spec.domain,
                    started_at=started_at,
                    approval_state=_approval_state(spec, "error", exc.code),
                )
            )
            return normalize_error(spec, exc)

        envelope = normalize_result(spec, raw)
        if spec.read_only:
            self._ctx.cache[cache_key] = raw
        envelope["metadata"]["cache_hit"] = False
        envelope["metadata"]["duration_ms"] = duration
        if retries:
            envelope["metadata"]["retries"] = retries
        if dropped:
            # Arguments the model tried to set that the tool does not accept.
            # Reported so the attempt is auditable, values never echoed.
            envelope["metadata"]["dropped_arguments"] = dropped
        self._record(
            MCPToolCallRecord(
                tool=spec.name,
                server=spec.server,
                provider=spec.provider,
                status="success",
                read_only=spec.read_only,
                requires_approval=spec.requires_approval,
                risk_level=spec.risk_level,
                duration_ms=duration,
                retries=retries,
                summary=summarize(spec, envelope),
                arguments=_safe_args(validated),
                run_id=self._ctx.run_id,
                domain=spec.domain,
                started_at=started_at,
                approval_state=_approval_state(spec, "success", None),
            )
        )
        return envelope

    def data(self, name: str, arguments: dict[str, Any] | None = None, **kw: Any) -> dict[str, Any]:
        """Convenience: invoke and return the normalized envelope's data.

        Raises ``MCPError`` on failure â€” used by server-side (non-LLM)
        callers that must not silently swallow an error.
        """
        envelope = self.call(name, arguments, **kw)
        if envelope.get("status") != "success":
            raise MCPError(
                (envelope.get("error") or {}).get("message", "tool failed"),
                code=(envelope.get("error") or {}).get("code", INTERNAL_ERROR),
                tool=name,
            )
        return envelope.get("data") or {}

    # â”€â”€ internals â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _invoke_with_retries(
        self, spec: MCPToolSpec, arguments: dict[str, Any], action_uuid: Any
    ) -> tuple[dict[str, Any] | None, int, MCPError | None]:
        """Bounded retry honouring a provider Retry-After hint.

        Only transient classes are retried, and never beyond the
        TIGHTER of the client-wide budget and this tool's declared
        ``max_retries``. Non-transient failures (auth, not-connected,
        approval) return immediately â€” retrying those cannot succeed and
        would stall the run.

        An EXTERNAL WRITE is never retried at all. Sending an email or
        creating a provider campaign is not idempotent, so a second attempt
        can duplicate a real-world side effect. Today
        ``action_service.execute_action`` would refuse the replay on its own
        state machine, but that safety lives in another module â€” the retry
        decision is made HERE, so the invariant is enforced here instead of
        being borrowed. A transient failure is reported once and the human
        can decide whether to re-approve.
        """
        budget = (
            0
            if spec.external_write
            else min(self._max_retries, max(0, int(spec.max_retries)))
        )
        attempts = 0
        retries = 0
        last: MCPError | None = None
        while True:
            attempts += 1
            try:
                raw = self._transport.invoke(
                    spec, self._ctx, arguments, action_uuid
                )
                return validate_output(spec, raw), retries, None
            except MCPError as exc:
                last = exc
            except TypeError as exc:
                # A handler that does not accept a validated argument is a
                # schema/handler mismatch â€” report it honestly, never guess.
                last = MCPError(
                    f"{spec.name}: {type(exc).__name__}",
                    code=VALIDATION_ERROR,
                    tool=spec.name,
                    provider=spec.provider,
                )
            except Exception as exc:  # noqa: BLE001 â€” failure isolation
                last = ProviderCallError(
                    f"{spec.name} failed: {type(exc).__name__}",
                    tool=spec.name,
                    provider=spec.provider,
                )
                log.warning("MCP tool %s raised %s", spec.name, type(exc).__name__)
            if not last.retryable or retries >= budget:
                return None, retries, last
            wait = min(
                float(last.retry_after) if last.retry_after else float(2 ** retries),
                MAX_RETRY_DELAY_SECONDS,
            )
            retries += 1
            log.info(
                "MCP retry %d/%d for %s after %.1fs (%s)",
                retries, self._max_retries, spec.name, wait, last.code,
            )
            try:
                self._sleep(wait)
            except Exception:  # pragma: no cover - defensive
                pass

    def _record(self, record: MCPToolCallRecord) -> None:
        self.records.append(record)
        if self._on_call is not None:
            try:
                self._on_call(record)
            except Exception:  # observability must never break a call
                log.debug("MCP on_call hook failed", exc_info=True)


def _approval_state(spec: MCPToolSpec, status: str, error_code: str | None) -> str:
    """Approval posture of one invocation, for observability only.

    Reads and local writes are never approval-relevant; an external write
    that succeeded necessarily passed the human-approval + execution gates
    (policy runs before dispatch), so "approved" is a fact, not a claim.
    """
    if spec.read_only or not spec.external_write:
        return "not_applicable"
    if status == "success":
        return "approved"
    if error_code == APPROVAL_REQUIRED:
        return "required"
    if error_code == EXECUTION_DISABLED:
        return "withheld"
    return "not_applicable"


def _as_uuid(value: Any) -> Any:
    if value is None or isinstance(value, str) and not value.strip():
        return None
    import uuid as _uuid

    if isinstance(value, _uuid.UUID):
        return value
    try:
        return _uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return value  # policy will reject it as tenant scope / missing


def _agent_domains(agent: str | None) -> tuple[str, ...] | None:
    """Capability domains an agent may discover.

    ``None`` means "no agent filter" (internal callers that legitimately see
    everything, e.g. the platform catalog endpoint). An agent that exists but
    was granted nothing gets an empty tuple, which yields an empty catalog.
    """
    if agent is None:
        return None
    from backend.app.integrations.mcp.domains import domains_for_agent

    return domains_for_agent(agent)


def _safe_args(arguments: dict[str, Any]) -> dict[str, Any]:
    """Bounded, redacted argument projection for observability."""
    return _redact(_truncate(arguments or {}))


__all__ = [
    "DEFAULT_MAX_RETRIES",
    "MCPClient",
    "MCPToolCallRecord",
    "normalize_error",
    "normalize_result",
    "summarize",
]