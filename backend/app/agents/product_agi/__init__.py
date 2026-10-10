"""Product Agent — an autonomous product-growth employee.

The second operational consumer of the shared MCP foundation after the
Marketing Agent. It owns a nine-stage cycle (see ``state.py``) and reaches
every piece of business data through the SAME ``MCPClient`` /
``MCPToolRegistry`` / policy / tenant context the Marketing Agent uses. It
adds no client, no registry, no policy, no credential store, no tenant
system, no approval system and no execution path.

Layout:

    state.py      stage machine + run state
    tools.py      stage -> MCP phase/tool map, tool allowlist
    schemas.py    structured LLM output contracts
    prompts.py    the reasoning prompts
    llm.py        Groq provider construction (reuses the shared provider)
    rag.py        research over the shared AgenticRAG loop
    agent.py      the cycle itself
    service.py    dashboard/read-model assembly
"""
from backend.app.agents.product_agi.state import (  # noqa: F401
    ProductAgentState,
    RunStatus,
    Stage,
)

__all__ = ["ProductAgentState", "RunStatus", "Stage"]