"""MCP tool contracts — the normalized shape every tool declares.

One dataclass (``MCPToolSpec``) is the single canonical declaration for a
tool's identity, capability, risk and guardrails. It is what the agent
sees in a prompt catalog and what policy/approval enforcement reads — so
the model can never learn a capability the policy layer does not enforce.

Every spec carries:

  name                    stable dotted name (domain.<capability>.<tool>)
  description             one honest sentence; never claims unverified data
  input_schema            JSON-Schema-shaped dict for argument validation
  output_schema           JSON-Schema-shaped dict describing the result
  read_only               True for pure reads (no external side effect)
  requires_approval       True for external writes
  requires_execution_enabled  True for external writes (EXECUTION_ENABLED)
  provider                internal | resend | google_ads | meta_ads | instagram
  requires_integration    integration key that must be connected, or None
  risk_level              low | medium | high | critical
  tenant_scoped           always True — MCP never crosses tenants
  timeout_seconds         declared per-tool latency budget
  max_retries             per-tool retry budget (client enforces the min
                          of this and the client-wide budget)
  handler                 server-side callable (never model-supplied)

Derived from the name (never declared twice):

  domain                  first segment — the OWNING capability domain:
                          "marketing", "commerce", "analytics" or
                          "product_intelligence". This is what
                          ``domains.capability_domain`` reads and what an
                          agent's capability grant is matched against.
  server                  second segment — the capability/provider. A channel
                          server keeps the three-segment
                          ``domain.<server>.<tool>`` shape; a
                          domain-namespaced read server (the Product Agent's
                          commerce / product_intelligence tools) uses
                          ``domain.<tool>`` and is served internally.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

RiskLevel = Literal["low", "medium", "high", "critical"]

#: Argument keys the model may NEVER supply. The merchant identity always
#: comes from the authenticated server context (MCPExecutionContext), never
#: from model output. Shared with the MarketingAGI sanitizer so both layers
#: reject the same thing.
FORBIDDEN_ARG_KEYS: frozenset[str] = frozenset(
    {
        "merchant_id",
        "merchant",
        "merchantId",
        "tenant_id",
        "tenant",
        "tenantId",
        "workspace_id",
        "db",
        "session",
        "llm",
        "embedding_provider",
        "access_token",
        "refresh_token",
        "api_key",
        "client_secret",
        "developer_token",
        "authorization",
    }
)

#: Guardrails that must never be satisfiable from tool arguments.
GUARDRAIL_ARG_KEYS: frozenset[str] = frozenset(
    {"requires_approval", "execution_enabled", "approved", "approved_by"}
)


@dataclass(frozen=True)
class MCPToolSpec:
    """Canonical declaration for one MCP tool."""

    name: str
    description: str
    provider: str
    handler: Callable[..., Any]
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    read_only: bool = True
    #: True when a write has an effect OUTSIDE this platform (a provider
    #: side effect). Such a write is approval-gated + execution-gated by
    #: construction. A local write (e.g. persisting a campaign draft) is
    #: still not read-only, but carries no external side effect, so it is
    #: declared ``external_write=False`` and keeps the pre-existing
    #: approval boundary unchanged.
    #:
    #: Defaults to False so a tool author must OPT IN to claiming an external
    #: side effect — that opt-in is what turns on the approval gate.
    external_write: bool = False
    requires_approval: bool = False
    requires_execution_enabled: bool = False
    requires_integration: str | None = None
    risk_level: RiskLevel = "low"
    tenant_scoped: bool = True
    phase: str = "research"
    #: Declared latency budget for one invocation (seconds). Enforced at
    #: the provider/transport layer (the existing integrations' HTTP
    #: timeouts); surfaced in the catalog so callers can reason about it.
    timeout_seconds: float = 30.0
    #: Per-tool retry budget. The client retries min(this, client-wide
    #: budget) and never retries a non-retryable error class.
    max_retries: int = 2
    legacy_tool_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or "." not in self.name:
            raise ValueError(
                f"MCP tool name must be dotted and stable, got {self.name!r}"
            )
        if not self.tenant_scoped:
            raise ValueError(
                f"MCP tool {self.name}: tenant_scoped cannot be disabled"
            )
        if self.timeout_seconds <= 0:
            raise ValueError(
                f"MCP tool {self.name}: timeout_seconds must be positive"
            )
        if self.max_retries < 0:
            raise ValueError(
                f"MCP tool {self.name}: max_retries cannot be negative"
            )
        if self.read_only:
            # A read-only tool must not claim an external side effect. Both
            # the approval gate (policy keys on read_only first) and the
            # read cache key on this flag, so this combination would be an
            # ungated, cacheable external write. Refuse to declare it.
            if self.external_write:
                raise ValueError(
                    f"MCP tool {self.name} is read-only but declares "
                    "external_write"
                )
            if self.requires_approval or self.requires_execution_enabled:
                raise ValueError(
                    f"MCP tool {self.name} is read-only but declares a "
                    "write guardrail"
                )
            return
        if self.external_write:
            if not self.requires_approval:
                raise ValueError(
                    f"MCP tool {self.name} is an external write without "
                    "requires_approval"
                )
            if not self.requires_execution_enabled:
                raise ValueError(
                    f"MCP tool {self.name} is an external write without "
                    "requires_execution_enabled"
                )
            if self.risk_level in ("low", "medium"):
                raise ValueError(
                    f"MCP tool {self.name} is an external write; risk_level "
                    "must be high or critical"
                )

    # ── derived declarations ─────────────────────────────────────────────

    @property
    def server(self) -> str:
        """Logical MCP server this tool belongs to."""
        return self.name.split(".", 2)[1] if self.name.count(".") >= 2 else "internal"

    @property
    def domain(self) -> str:
        """Owning domain (first name segment): marketing, commerce, ..."""
        return self.name.split(".", 1)[0]

    @property
    def internal(self) -> bool:
        return self.provider == "internal"

    def policy(self) -> dict[str, Any]:
        """Guardrail projection — the ONLY shape policy decisions read."""
        return {
            "name": self.name,
            "domain": self.domain,
            "provider": self.provider,
            "read_only": self.read_only,
            "external_write": self.external_write,
            "requires_approval": self.requires_approval,
            "requires_execution_enabled": self.requires_execution_enabled,
            "requires_integration": self.requires_integration,
            "risk_level": self.risk_level,
            "tenant_scoped": self.tenant_scoped,
            "phase": self.phase,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
        }

    def to_catalog_entry(self) -> dict[str, Any]:
        """LLM-safe catalog entry. NEVER includes the handler."""
        return {
            "name": self.name,
            "description": self.description,
            "domain": self.domain,
            "provider": self.provider,
            "phase": self.phase,
            "read_only": self.read_only,
            "requires_approval": self.requires_approval,
            "requires_integration": self.requires_integration,
            "risk_level": self.risk_level,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "input_schema": self.input_schema,
        }


__all__ = [
    "FORBIDDEN_ARG_KEYS",
    "GUARDRAIL_ARG_KEYS",
    "MCPToolSpec",
    "RiskLevel",
]