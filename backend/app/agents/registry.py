"""Agent registry — the single place agents are instantiated."""
from __future__ import annotations

from backend.app.agents.base import BaseGrowthAgent
from backend.app.agents.campaign_strategist import CampaignStrategistAgent
from backend.app.agents.customer_intelligence import CustomerIntelligenceAgent
from backend.app.agents.designer_agent import DesignerAgent
from backend.app.agents.discovery import GrowthDiscoveryAgent
from backend.app.agents.experiment_agent import ExperimentAgent
from backend.app.agents.manager_agent import ManagerAgent
from backend.app.agents.marketing_agent import MarketingAgent
from backend.app.agents.memory_agent import GrowthMemoryAgent
from backend.app.agents.payment_recovery import PaymentRecoveryAgent
from backend.app.agents.prioritization import OpportunityPrioritizationAgent
from backend.app.agents.product_agent import ProductAgent
from backend.app.agents.revenue_optimization import RevenueOptimizationAgent
from backend.app.agents.personalization_agent import PersonalizationAgent
from backend.app.agents.software_agent import SoftwareAgent

AGENT_INSTANCES: dict[str, BaseGrowthAgent] = {
    agent.NAME: agent
    for agent in (
        # Domain Specialist Agents (existing)
        GrowthDiscoveryAgent(),
        CustomerIntelligenceAgent(),
        RevenueOptimizationAgent(),
        CampaignStrategistAgent(),
        PaymentRecoveryAgent(),
        OpportunityPrioritizationAgent(),
        ExperimentAgent(),
        GrowthMemoryAgent(),
        # Main AI Growth Team Agents (Phase E)
        ManagerAgent(),
        MarketingAgent(),
        ProductAgent(),
        DesignerAgent(),
        SoftwareAgent(),
        # Personalization — per-customer next-best-action decisioning.
        # Not a debate participant (it produces decisions, not debate
        # turns); dispatched from the AI Team workspace like the specialists.
        PersonalizationAgent(),
    )
}

# Agent categories for clarity
DOMAIN_SPECIALIST_AGENTS = {
    "GrowthDiscoveryAgent",
    "CustomerIntelligenceAgent",
    "RevenueOptimizationAgent",
    "CampaignStrategistAgent",
    "PaymentRecoveryAgent",
    "OpportunityPrioritizationAgent",
    "ExperimentAgent",
    "GrowthMemoryAgent",
    "PersonalizationAgent",
}

MAIN_GROWTH_TEAM_AGENTS = {
    "ManagerAgent",
    "MarketingAgent",
    "ProductAgent",
    "DesignerAgent",
    "SoftwareAgent",
}


# Public metadata for /api/agents (permissions included for transparency)
def agent_catalog() -> list[dict]:
    """
    Registry-driven catalog for the AI Team dashboard.

    ``tools`` is now resolved through the canonical catalog
    (:mod:`backend.app.agents.catalog`) so every advertised id maps to a real,
    registered, callable implementation. Anything an agent still declares
    under a legacy name is translated via ``LEGACY_TOOL_ALIASES`` and
    reported in ``unimplemented_tools`` rather than silently presented as a
    capability it does not have.
    """
    from backend.app.agents.catalog import (
        LEGACY_TOOL_ALIASES,
        TOOL_REGISTRY,
    )
    from backend.app.agents.permissions import FORBIDDEN_CAPABILITIES

    entries: list[dict] = []
    for agent in AGENT_INSTANCES.values():
        resolved: list[str] = []
        unimplemented: list[str] = []
        for declared in agent.TOOLS:
            mapped = LEGACY_TOOL_ALIASES.get(declared, declared)
            if mapped in TOOL_REGISTRY:
                if mapped not in resolved:
                    resolved.append(mapped)
            else:
                unimplemented.append(declared)
        entries.append(
            {
                "name": agent.NAME,
                "description": agent.DESCRIPTION,
                "category": (
                    "main_growth_team"
                    if agent.NAME in MAIN_GROWTH_TEAM_AGENTS
                    else "domain_specialist"
                ),
                "permissions": sorted(agent.PERMISSIONS),
                "tools": resolved,
                "unimplemented_tools": unimplemented,
                "tool_details": [
                    TOOL_REGISTRY[t].to_dict() for t in resolved
                ],
                "can_approve": False,
                "can_execute": False,
                "forbidden_capabilities": sorted(FORBIDDEN_CAPABILITIES),
            }
        )
    return entries


def get_main_growth_team() -> list[BaseGrowthAgent]:
    """Return the 5 main AI Growth Team agents."""
    return [AGENT_INSTANCES[name] for name in MAIN_GROWTH_TEAM_AGENTS]


def get_domain_specialists() -> list[BaseGrowthAgent]:
    """Return the 8 domain specialist agents."""
    return [AGENT_INSTANCES[name] for name in DOMAIN_SPECIALIST_AGENTS]
