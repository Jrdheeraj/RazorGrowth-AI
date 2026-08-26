"""Agent registry — the single place agents are instantiated."""
from __future__ import annotations

from backend.app.agents.base import BaseGrowthAgent
from backend.app.agents.campaign_strategist import CampaignStrategistAgent
from backend.app.agents.customer_intelligence import CustomerIntelligenceAgent
from backend.app.agents.discovery import GrowthDiscoveryAgent
from backend.app.agents.experiment_agent import ExperimentAgent
from backend.app.agents.memory_agent import GrowthMemoryAgent
from backend.app.agents.payment_recovery import PaymentRecoveryAgent
from backend.app.agents.prioritization import OpportunityPrioritizationAgent
from backend.app.agents.revenue_optimization import RevenueOptimizationAgent

AGENT_INSTANCES: dict[str, BaseGrowthAgent] = {
    agent.NAME: agent
    for agent in (
        GrowthDiscoveryAgent(),
        CustomerIntelligenceAgent(),
        RevenueOptimizationAgent(),
        CampaignStrategistAgent(),
        PaymentRecoveryAgent(),
        OpportunityPrioritizationAgent(),
        ExperimentAgent(),
        GrowthMemoryAgent(),
    )
}

# Public metadata for /api/agents (permissions included for transparency)
def agent_catalog() -> list[dict]:
    from backend.app.agents.permissions import FORBIDDEN_CAPABILITIES

    return [
        {
            "name": agent.NAME,
            "description": agent.DESCRIPTION,
            "permissions": sorted(agent.PERMISSIONS),
            "tools": list(agent.TOOLS),
            "can_approve": False,
            "can_execute": False,
            "forbidden_capabilities": sorted(FORBIDDEN_CAPABILITIES),
        }
        for agent in AGENT_INSTANCES.values()
    ]
