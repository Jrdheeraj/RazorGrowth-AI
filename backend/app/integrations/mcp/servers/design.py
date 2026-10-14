"""MCP design server — the Designer Agent's workspace capabilities.

Registers real, working tools over the design tables. Every handler delegates
to ``DesignerService``, which already filters ``merchant_id`` in SQL, so the
tenant boundary is the existing one rather than a second implementation.

WHAT IS AND IS NOT REGISTERED
------------------------------
This build ships NO image-generation provider, so there is deliberately no
``design.image.generate`` tool. Registering one would mean advertising a
capability that cannot run. ``design.image.status`` IS registered because
answering "is image generation available?" honestly is a real, useful
capability — it reports ``unavailable`` with a reason.

Every tool here is INTERNAL and tenant-scoped. There is no external write in
this server, so none of these tools is approval-gated or execution-gated: a
tool that only reads and stores records inside this platform has no external
side effect. Anything that would reach an external provider belongs to a
different domain and must go through the existing action pipeline.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from backend.app.integrations.mcp.context import MCPExecutionContext
from backend.app.integrations.mcp.errors import MCPError
from backend.app.integrations.mcp.schemas import MCPToolSpec

MCP_SERVER = "design"


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": required or [],
        "additionalProperties": False,
    }


def _fallback_ctx(db: Session, merchant_id: uuid.UUID) -> MCPExecutionContext:
    """Context for a direct handler call that bypassed the client."""
    return MCPExecutionContext(db=db, merchant_id=merchant_id)


def _ctx(context: Any, db: Session, merchant_id: uuid.UUID) -> MCPExecutionContext:
    return context if context is not None else _fallback_ctx(db, merchant_id)


def _parse_uuid(value: Any, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise MCPError(
            f"{field} must be a UUID", code="INVALID_ARGUMENT", tool="design.workspace"
        ) from exc


# ── handlers ─────────────────────────────────────────────────────────────


def _list_projects(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
    limit: int = 20,
    project_type: str | None = None,
) -> dict[str, Any]:
    """Real design projects for THIS merchant."""
    from backend.app.services.designer_service import DesignerService

    ctx = _ctx(context, db, merchant_id)
    svc = DesignerService(ctx.db)
    rows = svc.list_projects(
        ctx.merchant_id, project_type=project_type, limit=min(int(limit), 100)
    )
    return {
        "count": len(rows),
        "projects": [
            {
                "id": str(p.id),
                "title": p.title,
                "project_type": p.project_type,
                "status": p.status.value,
                "analysis_cycle_id": p.analysis_cycle_id,
                "debate_id": str(p.debate_id) if p.debate_id else None,
                "created_at": p.created_at.isoformat(),
            }
            for p in rows
        ],
    }


def _get_project(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
    project_id: str,
) -> dict[str, Any]:
    """One project plus its current brief and asset counts."""
    from backend.app.services.designer_service import DesignerNotFound, DesignerService

    ctx = _ctx(context, db, merchant_id)
    svc = DesignerService(ctx.db)
    try:
        project = svc.get_project(ctx.merchant_id, _parse_uuid(project_id, "project_id"))
    except DesignerNotFound as exc:
        raise MCPError(
            "design project not found for this workspace",
            code="NOT_FOUND",
            tool="design.workspace.get_project",
        ) from exc
    brief = svc.get_current_brief(ctx.merchant_id, project.id)
    assets = svc.list_assets(ctx.merchant_id, project_id=project.id)
    return {
        "id": str(project.id),
        "title": project.title,
        "objective": project.objective,
        "project_type": project.project_type,
        "status": project.status.value,
        "analysis_cycle_id": project.analysis_cycle_id,
        "source_signal_id": project.source_signal_id,
        "source_opportunity_id": (
            str(project.source_opportunity_id) if project.source_opportunity_id else None
        ),
        "current_brief": (
            {
                "id": str(brief.id),
                "version": brief.version,
                "title": brief.title,
                "review_status": brief.review_status.value,
                "layout_direction": brief.layout_direction,
                "variant_count": len(brief.variants or []),
                "evidence_count": len(brief.evidence or []),
            }
            if brief is not None
            else None
        ),
        "asset_count": len(assets),
    }


def _get_brief(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
    brief_id: str,
) -> dict[str, Any]:
    """One stored creative brief, including its evidence provenance."""
    from backend.app.services.designer_service import DesignerNotFound, DesignerService

    ctx = _ctx(context, db, merchant_id)
    svc = DesignerService(ctx.db)
    try:
        brief = svc.get_brief(ctx.merchant_id, _parse_uuid(brief_id, "brief_id"))
    except DesignerNotFound as exc:
        raise MCPError(
            "creative brief not found for this workspace",
            code="NOT_FOUND",
            tool="design.workspace.get_brief",
        ) from exc
    return {
        "id": str(brief.id),
        "project_id": str(brief.project_id),
        "version": brief.version,
        "is_current": bool(brief.is_current),
        "title": brief.title,
        "objective": brief.objective,
        "audience": brief.audience,
        "channel": brief.channel,
        "layout_direction": brief.layout_direction,
        "color_guidance": brief.color_guidance,
        "typography_guidance": brief.typography_guidance,
        "variants": brief.variants or [],
        "evidence": brief.evidence or [],
        "radar_references": brief.radar_references or [],
        "open_questions": brief.open_questions or [],
        "review_status": brief.review_status.value,
        "confidence": float(brief.confidence) if brief.confidence is not None else None,
    }


def _list_assets(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
    project_id: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Real design assets, discriminated by honest kind.

    ``image_generation`` is included precisely so a caller can tell a brief
    from a rendered image instead of assuming one.
    """
    from backend.app.services.designer_service import DesignerService

    ctx = _ctx(context, db, merchant_id)
    svc = DesignerService(ctx.db)
    pid = _parse_uuid(project_id, "project_id") if project_id else None
    rows = svc.list_assets(ctx.merchant_id, project_id=pid, limit=min(int(limit), 100))
    return {
        "count": len(rows),
        "assets": [
            {
                "id": str(a.id),
                "project_id": str(a.project_id),
                "kind": a.kind.value,
                "title": a.title,
                "variant_key": a.variant_key,
                "review_status": a.review_status.value,
                "version_count": a.version_count,
                "current_version_id": (
                    str(a.current_version_id) if a.current_version_id else None
                ),
                "image_generation": a.image_generation,
            }
            for a in rows
        ],
    }


def _image_status(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
) -> dict[str, Any]:
    """Whether image generation is actually available.

    This build configures no provider, so the honest answer is
    ``unavailable`` plus a reason. A caller that needs an image must not
    substitute a brief for one.
    """
    from backend.app.services.designer_service import DesignerService

    ctx = _ctx(context, db, merchant_id)
    return DesignerService(ctx.db).image_generation_status()


# ── tool declarations ────────────────────────────────────────────────────


def TOOLS() -> list[MCPToolSpec]:
    _ID = {"type": "string", "format": "uuid", "description": "Record identifier."}
    return [
        MCPToolSpec(
            name="design.workspace.list_projects",
            description=(
                "List this workspace's real design projects with their type, "
                "status and linked AI Team cycle."
            ),
            provider="internal",
            handler=_list_projects,
            input_schema=_schema(
                {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                    "project_type": {"type": "string", "description": "Optional type filter."},
                }
            ),
            read_only=True,
            risk_level="low",
            phase="observe",
        ),
        MCPToolSpec(
            name="design.workspace.get_project",
            description=(
                "Read one design project with its current brief and asset "
                "counts. Returns not-found for another tenant's project."
            ),
            provider="internal",
            handler=_get_project,
            input_schema=_schema({"project_id": dict(_ID)}, ["project_id"]),
            read_only=True,
            risk_level="low",
            phase="observe",
        ),
        MCPToolSpec(
            name="design.workspace.get_brief",
            description=(
                "Read a stored creative brief with its evidence provenance, "
                "variants and open questions."
            ),
            provider="internal",
            handler=_get_brief,
            input_schema=_schema({"brief_id": dict(_ID)}, ["brief_id"]),
            read_only=True,
            risk_level="low",
            phase="research",
        ),
        MCPToolSpec(
            name="design.workspace.list_assets",
            description=(
                "List design assets with their kind (brief / specification / "
                "variant / rendered_image) and real image-generation status."
            ),
            provider="internal",
            handler=_list_assets,
            input_schema=_schema(
                {
                    "project_id": {**dict(_ID), "description": "Optional project filter."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                }
            ),
            read_only=True,
            risk_level="low",
            phase="research",
        ),
        MCPToolSpec(
            name="design.image.status",
            description=(
                "Report whether image generation is available. Returns "
                "'unavailable' with a reason when no provider is configured; "
                "it never returns an image URL."
            ),
            provider="internal",
            handler=_image_status,
            input_schema=_schema({}),
            read_only=True,
            risk_level="low",
            phase="research",
        ),
    ]


__all__ = ["MCP_SERVER", "TOOLS"]
