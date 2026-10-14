"""MCP tool registry — the allowlisted catalog of namespaced tools.

One registry holds every MCP tool the Marketing Agent may invoke. There is
no dynamic registration at runtime: a tool must be declared here with its
handler, provider, schemas and guardrail flags, otherwise the model cannot
select it and ``client.call`` refuses it.

Discovery is phase-scoped so the model is never handed the whole catalog:
``catalog(phase=...)`` returns only what that phase legitimately needs.
Filtering NEVER grants or removes execution capability — ``call`` always
validates against the complete registry.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Iterable

from backend.app.integrations.mcp.errors import ToolNotAllowedError
from backend.app.integrations.mcp.schemas import MCPToolSpec

log = logging.getLogger(__name__)

#: Phase-specific visibility. Keeps LLM prompts small (the previous
#: whole-catalog-per-call problem) without shrinking the allowlist.
PHASES: tuple[str, ...] = (
    "observe",
    "research",
    "campaign_prep",
    "execution",
)


def _visible_phases(phase: str) -> frozenset[str]:
    """Tool phases a given agent phase may see.

    Research is the deepening of observation, so it sees observation tools
    too; campaign preparation additionally sees the research tools. This is
    what keeps each prompt small while never removing a capability the
    agent legitimately needs at that stage.
    """
    if phase == "observe":
        return frozenset({"observe", "research"})
    if phase == "research":
        return frozenset({"research", "observe"})
    if phase == "campaign_prep":
        return frozenset({"campaign_prep", "research", "observe"})
    return frozenset({phase})


class MCPToolRegistry:
    """Allowlisted registry of MCP tools."""

    def __init__(self) -> None:
        self._specs: dict[str, MCPToolSpec] = {}
        # Legacy MarketingAGI tool name -> MCP tool name, so the existing
        # registry and the MCP catalog stay reconciled during migration.
        self._aliases: dict[str, str] = {}
        self._lock = threading.Lock()

    # ── registration ─────────────────────────────────────────────────────

    def register(self, spec: MCPToolSpec, *, alias: str | None = None) -> None:
        with self._lock:
            if spec.name in self._specs:
                if alias:
                    self._aliases.setdefault(alias, spec.name)
                    return
                raise ToolNotAllowedError(f"MCP tool already registered: {spec.name}")
            self._specs[spec.name] = spec
            if alias:
                self._aliases[alias] = spec.name

    def add_alias(self, alias: str, mcp_name: str) -> None:
        """Point a legacy MarketingAGI tool name at an MCP tool."""
        with self._lock:
            if mcp_name not in self._specs:
                raise ToolNotAllowedError(
                    f"Cannot alias {alias!r}: {mcp_name!r} is not registered"
                )
            if alias in self._specs:
                return
            self._aliases[alias] = mcp_name

    def register_all(self, specs: Iterable[MCPToolSpec]) -> None:
        for spec in specs:
            try:
                self.register(spec)
            except ToolNotAllowedError:
                # Idempotent bootstrap: re-running registration is expected
                # (the agent, RAG and the API each may trigger it). A
                # COLLISION between two different servers is a bug, so it
                # is logged rather than silently dropping a tool from the
                # catalog, the allowlists and the policy view.
                log.warning(
                    "MCP tool %s already registered - duplicate declaration "
                    "ignored; check for a name collision between MCP servers",
                    spec.name,
                )
                continue

    # ── lookup ───────────────────────────────────────────────────────────

    def spec(self, name: str) -> MCPToolSpec:
        """Resolve a tool name (MCP name or legacy alias) or refuse."""
        if name in self._specs:
            return self._specs[name]
        aliased = self._aliases.get(name)
        if aliased is not None:
            return self._specs[aliased]
        raise ToolNotAllowedError(
            f"Unknown MCP tool: {name!r}. The Marketing Agent may only "
            f"invoke tools registered in RazorGrowth AI.",
            tool=name,
            details={"registered_count": len(self._specs)},
        )

    def has(self, name: str) -> bool:
        return name in self._specs or name in self._aliases

    def all_specs(self) -> list[MCPToolSpec]:
        return list(self._specs.values())

    def names(self) -> list[str]:
        return sorted(self._specs)

    def mcp_name_for(self, legacy_name: str) -> str | None:
        """MCP name for a legacy MarketingAGI tool name, if aliased."""
        return self._aliases.get(legacy_name)

    def legacy_names(self) -> dict[str, str]:
        return dict(self._aliases)

    # ── discovery ────────────────────────────────────────────────────────

    def catalog(
        self,
        *,
        phase: str | None = None,
        include_write: bool = True,
        only_providers: Iterable[str] | None = None,
        domains: Iterable[str] | None = None,
        stage_tools: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        """LLM-safe catalog for one phase and/or domain set.

        ``only_providers`` drops tools whose provider is currently
        disconnected so the model never reasons over unavailable live
        data. ``domains`` narrows to capability domains, which is how each
        agent sees only what it was granted (see domains.AGENT_CAPABILITIES).
        ``stage_tools`` narrows further to an explicit set of tool names,
        which is how an agent keeps each of its own stages prompt-minimal
        on top of the platform phases.

        Filtering NEVER grants or removes execution capability - ``call``
        always validates against the complete registry.
        """
        from backend.app.integrations.mcp.domains import capability_domain

        providers = set(only_providers) if only_providers is not None else None
        wanted = set(domains) if domains is not None else None
        stage_wanted = set(stage_tools) if stage_tools is not None else None
        out: list[dict[str, Any]] = []
        for spec in self._specs.values():
            if stage_wanted is not None and spec.name not in stage_wanted:
                continue
            if phase == "execution":
                # Execution exposes ONLY the external write tools — the ones
                # that touch a provider. A local draft write belongs to
                # campaign preparation, not execution. The client still
                # refuses every one of them without human approval.
                if spec.read_only or not spec.external_write:
                    continue
            elif phase and spec.phase not in _visible_phases(phase):
                continue
            if not include_write and not spec.read_only:
                continue
            if (
                providers is not None
                and not spec.internal
                and spec.requires_integration
                and spec.requires_integration not in providers
            ):
                continue
            entry = spec.to_catalog_entry()
            entry["capability_domain"] = capability_domain(spec.name)
            if wanted is not None and entry["capability_domain"] not in wanted:
                continue
            out.append(entry)
        return out

    def catalog_for_agent(
        self,
        agent: str,
        *,
        phase: str | None = None,
        include_write: bool = True,
        stage_tools: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Catalog an agent is granted, by capability domain.

        An unknown agent gets an EMPTY catalog rather than everything: fail
        closed, so a newly added agent cannot accidentally see the whole
        platform until it is granted domains.
        """
        from backend.app.integrations.mcp.domains import domains_for_agent

        return self.catalog(
            phase=phase,
            include_write=include_write,
            domains=domains_for_agent(agent),
            stage_tools=stage_tools,
        )

    def names_for_agent(self, agent: str) -> list[str]:
        """Canonical tool names an agent may discover."""
        return [e["name"] for e in self.catalog_for_agent(agent)]

    def policies(self, *, names: Iterable[str] | None = None) -> list[dict[str, Any]]:
        specs = (
            [self.spec(n) for n in names] if names is not None else self.all_specs()
        )
        return [s.policy() for s in specs]


_REGISTRY = MCPToolRegistry()
_BOOTSTRAPPED = False
_BOOTSTRAP_LOCK = threading.Lock()


def get_mcp_registry() -> MCPToolRegistry:
    """Return the singleton registry, bootstrapping it on first use."""
    global _BOOTSTRAPPED
    if not _BOOTSTRAPPED:
        bootstrap_mcp_tools()
    return _REGISTRY


def bootstrap_mcp_tools() -> MCPToolRegistry:
    """Idempotently register every MCP server's tools."""
    global _BOOTSTRAPPED
    with _BOOTSTRAP_LOCK:
        if _BOOTSTRAPPED:
            return _REGISTRY
        from backend.app.integrations.mcp.servers import analytics_product as analytics_product_server
        from backend.app.integrations.mcp.servers import commerce as commerce_server
        from backend.app.integrations.mcp.servers import design as design_server
        from backend.app.integrations.mcp.servers import email as email_server
        from backend.app.integrations.mcp.servers import google_ads as google_ads_server
        from backend.app.integrations.mcp.servers import instagram as instagram_server
        from backend.app.integrations.mcp.servers import internal_marketing as internal_server
        from backend.app.integrations.mcp.servers import meta_ads as meta_ads_server
        from backend.app.integrations.mcp.servers import product_intelligence as product_intelligence_server

        for module in (
            internal_server,
            email_server,
            google_ads_server,
            meta_ads_server,
            instagram_server,
            commerce_server,
            analytics_product_server,
            product_intelligence_server,
            design_server,
        ):
            _REGISTRY.register_all(module.TOOLS())
            # Only servers that re-expose a legacy MarketingAGI tool name
            # declare ALIASES; a server with no legacy names simply omits it.
            for legacy, mcp_name in getattr(module, "ALIASES", {}).items():
                try:
                    _REGISTRY.add_alias(legacy, mcp_name)
                except ToolNotAllowedError:
                    log.warning("MCP alias %s -> %s not applied", legacy, mcp_name)
        _BOOTSTRAPPED = True
        from backend.app.integrations.mcp import policy as _policy

        _policy._refresh_allowlists()
        return _REGISTRY


def reset_for_tests() -> None:
    """Clear the singleton so a fresh bootstrap runs (tests only)."""
    global _BOOTSTRAPPED
    from backend.app.integrations.mcp import policy as _policy

    with _BOOTSTRAP_LOCK:
        _REGISTRY.__init__()  # type: ignore[misc]
        _BOOTSTRAPPED = False
        _policy.MARKETING_READ_TOOLS = frozenset()
        _policy.MARKETING_WRITE_TOOLS = frozenset()
        _policy.MARKETING_APPROVAL_REQUIRED_TOOLS = frozenset()
        _policy.MARKETING_INTERNAL_TOOLS = frozenset()
        _policy.MARKETING_EXTERNAL_TOOLS = frozenset()
        _policy._ALLOWLISTS_INITIALISED = False


__all__ = [
    "MCPToolRegistry",
    "PHASES",
    "bootstrap_mcp_tools",
    "get_mcp_registry",
    "reset_for_tests",
]