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
    from backend.app.agents.permissions import FORBIDDEN_CAPABILITIES

    return [
        {
            "name": agent.NAME,
            "description": agent.DESCRIPTION,
            "category": "main_growth_team" if agent.NAME in MAIN_GROWTH_TEAM_AGENTS else "domain_specialist",
            "permissions": sorted(agent.PERMISSIONS),
            "tools": list(agent.TOOLS),
            "can_approve": False,
            "can_execute": False,
            "forbidden_capabilities": sorted(FORBIDDEN_CAPABILITIES),
        }
        for agent in AGENT_INSTANCES.values()
    ]


def get_main_growth_team() -> list[BaseGrowthAgent]:
    """Return the 5 main AI Growth Team agents."""
    return [AGENT_INSTANCES[name] for name in MAIN_GROWTH_TEAM_AGENTS]


def get_domain_specialists() -> list[BaseGrowthAgent]:
    """Return the 8 domain specialist agents."""
    return [AGENT_INSTANCES[name] for name in DOMAIN_SPECIALIST_AGENTS]
