"""MCP — standardized tool connectivity underneath the Marketing Agent.

The Marketing Agent stays the agent: the LLM reasons, Agentic RAG retrieves,
the approval/verification/audit pipeline governs. MCP is only the
standardized way tools are exposed and invoked:

    MarketingAGI → LLM reasoning → Agentic RAG → MCP tool layer
                 → internal tools / Resend / Google Ads / Meta Ads / Instagram

Guarantees this package upholds:

  - RazorGrowth AI owns tenant isolation, authorization, the tool
    allowlist, human approval, verification, execution policy and audit
  - the model selects from a phase-scoped catalog; an unregistered name is
    refused and recorded
  - credentials are resolved server-side from the existing vault and can
    never appear in an argument, a result, a log line or the prompt
  - external writes require a human-approved action AND EXECUTION_ENABLED
  - a provider failure is reported as a classified failure, never a
    fabricated success
"""

from backend.app.integrations.mcp.client import (
    MCPClient,
    MCPToolCallRecord,
    normalize_error,
    normalize_result,
)
from backend.app.integrations.mcp.context import MCPExecutionContext
from backend.app.integrations.mcp.errors import (
    ERROR_CODES,
    MCPError,
    ProviderCallError,
    classify_provider_code,
)
from backend.app.integrations.mcp.registry import (
    MCPToolRegistry,
    PHASES,
    bootstrap_mcp_tools,
    get_mcp_registry,
)
from backend.app.integrations.mcp.schemas import MCPToolSpec
from backend.app.integrations.mcp.transport import InProcessTransport, MCPTransport

__all__ = [
    "ERROR_CODES",
    "InProcessTransport",
    "MCPClient",
    "MCPError",
    "MCPExecutionContext",
    "MCPToolCallRecord",
    "MCPToolRegistry",
    "MCPToolSpec",
    "MCPTransport",
    "PHASES",
    "ProviderCallError",
    "bootstrap_mcp_tools",
    "classify_provider_code",
    "get_mcp_registry",
    "normalize_error",
    "normalize_result",
]