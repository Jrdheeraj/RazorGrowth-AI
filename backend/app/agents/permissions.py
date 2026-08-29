"""
Agent capability permissions — Phase 5 Feature 13.

Every specialised agent declares exactly what it may do. The registry is
the single source of truth used by the orchestrator, the /api/agents
endpoint, and the test suite.

INVARIANTS (enforced by tests, respected by construction):
  - NO agent ever holds approve_action or execute_action.
  - propose_action means "create a Phase 4 AgentAction in 'requested'
    state" — approval remains human-only downstream.
  - No capability implies direct DB mutation outside repository services.
"""
from __future__ import annotations

# ── capability vocabulary ───────────────────────────────────────────────────
READ_MERCHANT = "read_merchant"
READ_CUSTOMERS = "read_customers"
READ_ORDERS = "read_orders"
READ_PAYMENTS = "read_payments"
READ_PRODUCTS = "read_products"
READ_OPPORTUNITIES = "read_opportunities"
READ_CAMPAIGNS = "read_campaigns"
READ_MEMORY = "read_memory"
WRITE_MEMORY = "write_memory"
SIMULATE = "simulate"
PROPOSE_ACTION = "propose_action"

# Capabilities that must NEVER appear in any agent's permission set.
FORBIDDEN_CAPABILITIES: frozenset[str] = frozenset(
    {
        "approve_action",
        "execute_action",
        "reject_action",
        "bypass_guardrails",
        "direct_database_mutation",
        "send_money",
    }
)


class AgentPermissionError(PermissionError):
    """Raised when an agent attempts a capability it does not hold."""


AGENT_PERMISSIONS: dict[str, frozenset[str]] = {
    # ── Domain Specialist Agents (existing) ─────────────────────────────────
    "GrowthDiscoveryAgent": frozenset(
        {
            READ_MERCHANT, READ_CUSTOMERS, READ_ORDERS,
            READ_PAYMENTS, READ_PRODUCTS, READ_OPPORTUNITIES,
        }
    ),
    "CustomerIntelligenceAgent": frozenset(
        {READ_MERCHANT, READ_CUSTOMERS, READ_ORDERS, READ_PAYMENTS}
    ),
    "PaymentRecoveryAgent": frozenset(
        {READ_PAYMENTS, READ_CUSTOMERS, SIMULATE, PROPOSE_ACTION}
    ),
    "CampaignStrategistAgent": frozenset(
        {READ_CUSTOMERS, READ_OPPORTUNITIES, READ_CAMPAIGNS, SIMULATE, PROPOSE_ACTION}
    ),
    "RevenueOptimizationAgent": frozenset(
        {READ_OPPORTUNITIES, READ_ORDERS, SIMULATE, PROPOSE_ACTION}
    ),
    "OpportunityPrioritizationAgent": frozenset({READ_OPPORTUNITIES}),
    "ExperimentAgent": frozenset({READ_OPPORTUNITIES, READ_CUSTOMERS}),
    "GrowthMemoryAgent": frozenset({READ_MEMORY, WRITE_MEMORY}),

    # ── Main AI Growth Team Agents (Phase E) ────────────────────────────────
    "ManagerAgent": frozenset({
        READ_MERCHANT, READ_CUSTOMERS, READ_ORDERS, READ_PAYMENTS, SIMULATE,
    }),
    "MarketingAgent": frozenset({
        READ_MERCHANT, READ_CUSTOMERS, READ_ORDERS, READ_CAMPAIGNS, READ_OPPORTUNITIES, SIMULATE, PROPOSE_ACTION,
    }),
    "ProductAgent": frozenset({
        READ_MERCHANT, READ_PRODUCTS, READ_ORDERS, READ_CUSTOMERS, READ_OPPORTUNITIES, SIMULATE, PROPOSE_ACTION,
    }),
    "DesignerAgent": frozenset({
        READ_MERCHANT, READ_CAMPAIGNS, READ_CUSTOMERS,
    }),
    "SoftwareAgent": frozenset({
        READ_MERCHANT, READ_ORDERS, READ_CUSTOMERS,
    }),
}


def has_permission(agent_name: str, capability: str) -> bool:
    perms = AGENT_PERMISSIONS.get(agent_name)
    return perms is not None and capability in perms


def assert_permission(agent_name: str, capability: str) -> None:
    if not has_permission(agent_name, capability):
        raise AgentPermissionError(
            f"{agent_name} does not hold capability '{capability}'. "
            f"Held: {sorted(AGENT_PERMISSIONS.get(agent_name, frozenset()))}"
        )
