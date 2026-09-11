"""MarketingAGI tools — registration entry point."""
from __future__ import annotations

from backend.app.agents.marketing_agi.tools.registry import get_registry
from backend.app.agents.marketing_agi.tools import (
    analytics_tools,
    customer_tools,
    product_tools,
    marketing_tools,
    knowledge_tools,
    integration_tools,
)


def register_all_tools() -> None:
    """Idempotently register every MarketingAGI tool."""
    registry = get_registry()
    if registry.catalog():
        return
    analytics_tools.register(registry)
    customer_tools.register(registry)
    product_tools.register(registry)
    marketing_tools.register(registry)
    knowledge_tools.register(registry)
    integration_tools.register(registry)
