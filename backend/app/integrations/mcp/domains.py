"""MCP domain taxonomy and per-agent capability profiles.

Agents are MCP CLIENTS. A domain is a group of capabilities that answers a
business question ("what is selling?", "which customers are at risk?",
"how are campaigns performing?"), NOT an agent. The Marketing Agent, the
Product Agent and Growth Radar are all consumers of the same registry; they
differ only in which domains they are granted.

This module is the shared vocabulary that makes that possible without
duplicating a client, a registry or a policy per agent:

  - ``MCPDomain``          a capability domain and its real status
  - ``DOMAINS``            the registry of domains
  - ``AGENT_CAPABILITIES`` which domains each agent may discover
  - ``capability_domain``  which domain an existing tool belongs to

DOMAIN STATUS IS HONEST
-----------------------
``OPERATIONAL``  tools exist and every one has a real implementation
``STRUCTURAL``   the domain is a supported, registrable target but has no
                 tools yet, because no capability is implemented for it

No domain is marked operational unless it exposes real, registered tools,
and no placeholder or mock tool is ever registered to make a domain look
complete. A future agent consumes a ``STRUCTURAL`` domain by adding real
tools to it - not by inheriting fake ones.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

# ── domain status ───────────────────────────────────────────────────────

OPERATIONAL = "operational"
STRUCTURAL = "structural"


@dataclass(frozen=True)
class MCPDomain:
    """A capability domain in the shared MCP platform."""

    name: str
    description: str
    status: str
    #: Agents granted this domain. Kept on the domain so the grant is
    #: visible in one place, but the registry is still the authority on
    #: which TOOLS exist.
    consumers: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        """True when the domain has real, registered tools."""
        return self.status == OPERATIONAL

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "available": self.available,
            "consumers": list(self.consumers),
        }


#: The five capability domains. ``status`` reflects what exists TODAY.
DOMAINS: dict[str, MCPDomain] = {
    d.name: d
    for d in (
        MCPDomain(
            name="marketing",
            description=(
                "Campaign execution and marketing channels: email/Resend, "
                "Google Ads, Meta Ads, Instagram."
            ),
            status=OPERATIONAL,
            consumers=("marketing_agent", "growth_radar"),
        ),
        MCPDomain(
            name="analytics",
            description=(
                "Measured commerce performance: revenue, orders, AOV, "
                "failed payments, retention, campaign performance."
            ),
            status=OPERATIONAL,
            consumers=(
                "marketing_agent",
                "product_agent",
                "growth_radar",
            ),
        ),
        MCPDomain(
            name="customer",
            description=(
                "Customer intelligence: search, profile, history, segments, "
                "activity and retention signals."
            ),
            status=OPERATIONAL,
            consumers=("marketing_agent", "growth_radar"),
        ),
        MCPDomain(
            name="commerce",
            description=(
                "Commerce primitives: products, catalog, orders, payments "
                "and stock."
            ),
            # Operational since the Product Agent's commerce server landed:
            # catalog, inventory, low-stock, per-product sales and orders are
            # real registered reads over this workspace's own products and
            # order_items tables.
            status=OPERATIONAL,
            consumers=("product_agent", "growth_radar"),
        ),
        MCPDomain(
            name="product_intelligence",
            description=(
                "Product-level diagnosis and opportunity: underperformers, "
                "low stock, pricing and merchandising opportunities."
            ),
            # Deterministic analysis over real catalog + order rows. No model
            # runs inside these tools, so a finding can always be traced to
            # the arithmetic that produced it.
            status=OPERATIONAL,
            consumers=("product_agent",),
        ),
    )
}

# ── agent capability profiles ───────────────────────────────────────────


@dataclass(frozen=True)
class AgentCapabilities:
    """What one agent is allowed to DISCOVER.

    Discovery is a capability grant, not an authorization decision: it
    shapes the prompt catalog only. ``client.call`` still validates against
    the complete registry, and policy still re-checks tenant, approval and
    execution for every invocation.
    """

    agent: str
    domains: tuple[str, ...]

    def grants(self, domain: str) -> bool:
        return domain in self.domains


#: Per-agent domain grants. Adding an agent here is the whole integration
#: cost for tool discovery - no second client, registry or policy.
AGENT_CAPABILITIES: dict[str, AgentCapabilities] = {
    # The Marketing Agent is the first operational consumer.
    "marketing_agent": AgentCapabilities(
        agent="marketing_agent",
        domains=("analytics", "customer", "marketing"),
    ),
    # Product Agent: commerce + analytics + product intelligence.
    "product_agent": AgentCapabilities(
        agent="product_agent",
        domains=("commerce", "analytics", "product_intelligence"),
    ),
    # Growth Radar watches everything.
    "growth_radar": AgentCapabilities(
        agent="growth_radar",
        domains=("analytics", "commerce", "customer", "marketing"),
    ),
}


def get_agent_capabilities(agent: str) -> AgentCapabilities | None:
    return AGENT_CAPABILITIES.get(agent)


def domains_for_agent(agent: str) -> tuple[str, ...]:
    caps = AGENT_CAPABILITIES.get(agent)
    return caps.domains if caps else ()


def domain(name: str) -> MCPDomain | None:
    return DOMAINS.get(name)


def domain_report() -> list[dict[str, object]]:
    """Domain inventory for the API/dashboard, including real status."""
    return [d.to_dict() for d in DOMAINS.values()]


# ── tool -> domain mapping ──────────────────────────────────────────────

#: Second name segment -> capability domain. The FIRST segment is the
#: owning product namespace (``marketing.``); this maps the capability
#: group inside it. Keeping the mapping explicit (rather than inventing new
#: tool names) means the 29 existing tools gain true domain awareness
#: without a rename that would break stored references.
_SERVER_DOMAIN: dict[str, str] = {
    # existing CRM capability group
    "crm": "customer",
    # existing analytics capability group
    "analytics": "analytics",
    # product-facing catalog / inventory group
    "commerce": "commerce",
    # deterministic product diagnosis group
    "product_intelligence": "product_intelligence",
    # marketing channels
    "email": "marketing",
    "google_ads": "marketing",
    "meta_ads": "marketing",
    "instagram": "marketing",
    # RAG / memory evidence sources over this workspace's own data
    "knowledge": "analytics",
}


def capability_domain(tool_name: str) -> str:
    """Capability domain for a tool name.

    Unknown capability groups fall back to the first name segment so a new
    server is never silently invisible to domain filtering.
    """
    parts = str(tool_name).split(".")
    if len(parts) >= 3:
        return _SERVER_DOMAIN.get(parts[1], parts[1])
    return parts[0] if parts else "internal"


def domains_for_tools(names: Iterable[str]) -> set[str]:
    return {capability_domain(n) for n in names}


__all__ = [
    "AGENT_CAPABILITIES",
    "DOMAINS",
    "OPERATIONAL",
    "STRUCTURAL",
    "AgentCapabilities",
    "MCPDomain",
    "capability_domain",
    "domain",
    "domain_report",
    "domains_for_agent",
    "domains_for_tools",
    "get_agent_capabilities",
]