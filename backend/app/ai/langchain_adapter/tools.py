"""
Canonical LangChain Tool Adapters for RazorGrowth AI.

Exposes every genuinely callable tool in backend.app.agents.catalog.TOOL_REGISTRY
as a typed LangChain BaseTool, preserving:
- Tenant isolation (merchant_id bound per session)
- Caller permission gating (caller_permissions)
- Pydantic input schema validation (args_schema)
- Idempotency & audit logging
- Read-only vs mutation safeguards
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional, Type

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from langchain_core.tools import BaseTool

from backend.app.agents.catalog import (
    LEGACY_TOOL_ALIASES,
    TOOL_REGISTRY,
    ToolSpec,
    get_tool,
    invoke,
    tool_ids_for_agent,
)
from backend.app.agents.registry import AGENT_INSTANCES

log = logging.getLogger(__name__)


class CanonicalLangChainTool(BaseTool):
    """LangChain BaseTool adapter for a RazorGrowth ToolSpec."""

    spec: ToolSpec = Field(description="Canonical ToolSpec from catalog")
    db: Any = Field(description="SQLAlchemy Session")
    merchant_id: uuid.UUID = Field(description="Authenticated tenant merchant UUID")
    caller_permissions: Optional[set[str]] = Field(default=None, description="Permissions held by caller agent")

    model_config = {
        "arbitrary_types_allowed": True,
    }

    def __init__(
        self,
        spec: ToolSpec,
        db: Session,
        merchant_id: uuid.UUID,
        caller_permissions: Optional[set[str]] = None,
        **kwargs: Any,
    ) -> None:
        name = spec.tool_id
        description = (
            f"{spec.summary} (Required permission: {spec.required_permission or 'None'}, "
            f"Read-only: {spec.read_only})"
        )
        args_schema: Type[BaseModel] = spec.input_model

        super().__init__(
            name=name,
            description=description,
            args_schema=args_schema,
            spec=spec,
            db=db,
            merchant_id=merchant_id,
            caller_permissions=caller_permissions,
            **kwargs,
        )

    def _run(self, **kwargs: Any) -> Any:
        """Synchronously execute tool via invoke with strict tenant gating."""
        try:
            # Ensure merchant_id in payload matches tenant boundary
            payload = dict(kwargs)
            payload["merchant_id"] = self.merchant_id

            res = invoke(
                self.spec.tool_id,
                db=self.db,
                arguments=payload,
                granted_permissions=self.caller_permissions or (),
            )
            # If the tool returned a Pydantic model, dump to dict for LLM readability
            if hasattr(res, "model_dump"):
                return res.model_dump()
            return res
        except Exception as exc:
            log.warning("CanonicalLangChainTool execution failed for %s: %s", self.spec.tool_id, exc)
            return {
                "status": "error",
                "tool_id": self.spec.tool_id,
                "error": str(exc),
            }

    async def _arun(self, **kwargs: Any) -> Any:
        return self._run(**kwargs)


def tool_spec_to_langchain_tool(
    spec: ToolSpec,
    db: Session,
    merchant_id: uuid.UUID,
    caller_permissions: Optional[set[str]] = None,
) -> CanonicalLangChainTool:
    """Convert a single ToolSpec into a LangChain BaseTool."""
    return CanonicalLangChainTool(
        spec=spec,
        db=db,
        merchant_id=merchant_id,
        caller_permissions=caller_permissions,
    )


def get_agent_langchain_tools(
    agent_name: str,
    db: Session,
    merchant_id: uuid.UUID,
) -> list[CanonicalLangChainTool]:
    """Retrieve all authorized LangChain tools for a given agent name.

    Resolves tools through the canonical catalog, filtering to only genuinely
    callable tools registered in TOOL_REGISTRY that match the agent's permissions.
    """
    agent = AGENT_INSTANCES.get(agent_name)
    if agent is None:
        log.warning("get_agent_langchain_tools: Unknown agent %s", agent_name)
        return []

    caller_perms = set(agent.PERMISSIONS) if hasattr(agent, "PERMISSIONS") else None
    tools: list[CanonicalLangChainTool] = []

    # Map declared tools and legacy aliases
    declared = getattr(agent, "TOOLS", ())
    resolved_ids: list[str] = []
    for item in declared:
        canonical_id = LEGACY_TOOL_ALIASES.get(item, item)
        if canonical_id in TOOL_REGISTRY and canonical_id not in resolved_ids:
            resolved_ids.append(canonical_id)

    # Also include any tools associated via tool_ids_for_agent if available
    for tid in tool_ids_for_agent(agent_name):
        if tid in TOOL_REGISTRY and tid not in resolved_ids:
            resolved_ids.append(tid)

    for tid in resolved_ids:
        spec = TOOL_REGISTRY[tid]
        # Verify permission
        if spec.required_permission and caller_perms and spec.required_permission not in caller_perms:
            continue
        tools.append(
            CanonicalLangChainTool(
                spec=spec,
                db=db,
                merchant_id=merchant_id,
                caller_permissions=caller_perms,
            )
        )

    return tools
