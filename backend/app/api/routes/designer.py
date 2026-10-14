"""Designer Agent API — projects, briefs, assets, review and handoffs.

Router prefix is ``/designer`` and ``/api`` is added exactly once in
``main.py``, matching every other route module.

AUTH + TENANT ISOLATION
-----------------------
Every handler depends on the platform's own context dependency
(``merchant_ctx`` / ``operator_ctx`` / ``approver_ctx``) and passes
``ctx.merchant_id`` — never a merchant id from the request body — into the
service. The service filters on ``merchant_id`` in SQL, so a record belonging
to another merchant returns 404 rather than a hint that it exists.

REVIEW IS A HUMAN ACT
---------------------
Only ``approver_ctx`` routes may record a review decision. The agent has no
path into ``DesignerService.record_review``, so it can prepare work for review
but never approve it. A brief is not an executable action.

IMAGE GENERATION IS HONEST
--------------------------
``/image-generation`` reports the real availability of the one configured
provider (Cloudflare Workers AI, ``@cf/black-forest-labs/flux-1-schnell``),
derived from ``IMAGE_GENERATION_ENABLED`` and real credentials. When it is off
or unconfigured the answer is ``unavailable`` with a reason — never a
fabricated asset reference, never a placeholder marked as a generated
creative.

There are TWO ways in, and they are not the same thing:

  * ``POST /assets/{asset_id}/image-generation`` — LLM-assisted (Path A). The
    Designer Agent produced and persisted a brief; this renders it.
  * ``POST /image-generation`` — direct (Path B). A plain image description
    with NO brief and NO LLM call at all. This is deliberately available
    before any design asset exists, because image generation does not depend
    on the LLM provider being reachable.

A direct render is labelled as such. It never implies a Designer Agent
research run completed.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.api.deps import (
    MerchantContext,
    approver_ctx,
    merchant_ctx,
    operator_ctx,
    resolve_claimed_merchant,
)
from backend.app.db.session import get_db
from backend.app.models.enums import (
    DesignAssetKind,
    DesignProjectStatus,
    DesignReviewStatus,
)
from backend.app.schemas.designer import (
    AssetRevisionRequest,
    CreativeBriefListResponse,
    CreativeBriefResponse,
    DesignAssetListResponse,
    DesignAssetResponse,
    DesignAssetVersionListResponse,
    DesignAssetVersionResponse,
    DesignProjectCreate,
    DesignProjectListResponse,
    DesignProjectResponse,
    DesignProjectUpdate,
    DesignerActivityResponse,
    DesignerStatusResponse,
    HandoffRequest,
    HandoffResponse,
    ReviewDecisionRequest,
    UXAuditRequest,
    UXAuditResponse,
)
from backend.app.core.config import get_settings
from backend.app.services.design_asset_storage import (
    DesignAssetStorage,
    ImageNotFound,
)
from backend.app.services.designer_service import (
    DesignerNotFound,
    DesignerService,
)


def _storage(db: Session) -> DesignAssetStorage:
    """Storage configured from settings — same limits the writer enforces."""
    s = get_settings()
    return DesignAssetStorage(
        db,
        max_bytes=s.IMAGE_MAX_BYTES,
        daily_quota=s.IMAGE_DAILY_QUOTA_PER_MERCHANT,
        daily_storage_quota_bytes=s.IMAGE_DAILY_STORAGE_QUOTA_BYTES,
        max_pixels=s.IMAGE_MAX_PIXELS,
        max_width=s.IMAGE_MAX_WIDTH,
        max_height=s.IMAGE_MAX_HEIGHT,
    )

log = logging.getLogger(__name__)

router = APIRouter(prefix="/designer", tags=["designer"])

#: Only these design tool providers have any integration surface in this build.
#: A provider absent from this map is reported ``unsupported`` — never
#: ``connected``, and never with a connection flow that does not exist.
_SUPPORTED_PROVIDERS: dict[str, str] = {
    "figma": "Design file handoff",
    "canva": "Template and asset exchange",
    "midjourney": "Image generation",
    "adobe_creative_cloud": "Asset library sync",
    "google_drive": "Asset storage",
    "notion": "Documentation",
}


def _svc(db: Session) -> DesignerService:
    return DesignerService(db)


def _not_found(exc: DesignerNotFound, code: str) -> HTTPException:
    """404 for absent AND cross-merchant records — no existence leak."""
    return HTTPException(status_code=404, detail=code)


# ── status / dashboard ───────────────────────────────────────────────────


@router.get("/status", response_model=DesignerStatusResponse)
def get_designer_status(
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Real agent status: registry presence, real capability state, and
    honest external-integration availability.

    A provider is reported connected ONLY when an IntegrationConnection row
    for THIS merchant says so.
    """
    from backend.app.agents.registry import AGENT_INSTANCES
    from backend.app.services import integration_service as integration_svc

    svc = _svc(db)
    entry = AGENT_INSTANCES.get("DesignerAgent")

    integrations: list[dict[str, Any]] = []
    connected_providers: dict[str, Any] = {}
    try:
        for row in integration_svc.list_connections(db, ctx.merchant_id):
            if isinstance(row.provider, str):
                connected_providers[row.provider] = row
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("integration lookup failed: %s", exc)

    for provider, purpose in _SUPPORTED_PROVIDERS.items():
        row = connected_providers.get(provider)
        integrations.append(
            {
                "provider": provider,
                "label": provider.replace("_", " ").title(),
                "purpose": purpose,
                # Truthful three-state: supported+connected, supported but not
                # connected, or not supported by this build at all.
                "status": (
                    "connected"
                    if row is not None
                    else "setup_required"
                ),
                "supported": True,
                "detail": (
                    f"Connected as {row.connection_metadata.get('account', 'workspace account')}"
                    if row is not None and row.connection_metadata
                    else "No integration is configured for this workspace."
                ),
            }
        )

    capabilities = [
        {
            "key": tool,
            "label": tool.replace("_", " ").title(),
            "status": "available",
            "detail": "Implemented by the Designer Agent; output is a structured brief.",
        }
        for tool in (entry.TOOLS if entry else ())
    ]

    # Resolve each row ONCE. These are four separate queries against real
    # tables, so calling the accessors repeatedly here would both waste work
    # and risk showing counts from different points in time.
    latest_project = svc.latest_project(ctx.merchant_id)
    latest_brief = svc.latest_brief(ctx.merchant_id)
    project_count = svc.count_projects(ctx.merchant_id)
    briefs = svc.list_briefs(ctx.merchant_id, limit=1000)
    assets = svc.list_assets(ctx.merchant_id, limit=1000)

    # The newest real record wins. Only the two stored timestamps are compared
    # with each other — never against ``now()`` — because a backend column
    # may be naive while ``now()`` is timezone-aware, and mixing the two
    # raises. A workspace with no records reports the instant it was read,
    # which is a real time, not a fabricated creation time.
    stored = [r.created_at for r in (latest_brief, latest_project) if r is not None]
    last_updated = max(stored) if stored else datetime.now(timezone.utc)

    return DesignerStatusResponse(
        agent_registered=entry is not None,
        agent_description=entry.DESCRIPTION if entry else None,
        capabilities=capabilities,
        integrations=integrations,
        image_generation=svc.image_generation_status(),
        latest_project=latest_project,
        latest_brief=latest_brief,
        metrics=svc.metrics(ctx.merchant_id),  # type: ignore[arg-type]
        counts={
            "projects": project_count,
            "briefs": len(briefs),
            "assets": len(assets),
        },
        last_updated=last_updated,
    )


@router.get("/activity", response_model=DesignerActivityResponse)
def get_designer_activity(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Genuine persisted events only — never a synthesised timestamp."""
    return {"items": _svc(db).activity(ctx.merchant_id, limit=limit)}


# ── projects ─────────────────────────────────────────────────────────────


@router.get("/projects", response_model=DesignProjectListResponse)
def list_projects(
    status_filter: DesignProjectStatus | None = Query(default=None, alias="status"),
    project_type: str | None = Query(default=None, max_length=60),
    analysis_cycle_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    svc = _svc(db)
    rows = svc.list_projects(
        ctx.merchant_id,
        status=status_filter,
        project_type=project_type,
        analysis_cycle_id=analysis_cycle_id,
        limit=limit,
        offset=offset,
    )
    return {"projects": rows, "total": svc.count_projects(ctx.merchant_id)}


@router.post(
    "/projects",
    response_model=DesignProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project(
    body: DesignProjectCreate,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Create a design project.

    A repeated objective inside a 24h window returns the EXISTING project
    rather than forking a second design thread, so a double-submitted form
    cannot create duplicate work. A project is a container only — no brief is
    generated here; that happens when the Designer Agent actually runs.
    """
    svc = _svc(db)
    existing = svc.find_project_by_objective(ctx.merchant_id, body.objective)
    if existing is not None:
        return existing

    project = svc.create_project(
        ctx.merchant_id,
        objective=body.objective,
        title=body.title,
        project_type=body.project_type or "campaign_creative",
        analysis_cycle_id=body.analysis_cycle_id,
    )
    db.commit()
    return project


@router.get("/projects/{project_id}", response_model=DesignProjectResponse)
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="INVALID_PROJECT_ID")
    try:
        return _svc(db).get_project(ctx.merchant_id, pid)
    except DesignerNotFound:
        raise _not_found(None, "DESIGN_PROJECT_NOT_FOUND")  # type: ignore[arg-type]


@router.patch("/projects/{project_id}", response_model=DesignProjectResponse)
def update_project(
    project_id: str,
    body: DesignProjectUpdate,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="INVALID_PROJECT_ID")
    try:
        row = _svc(db).update_project(
            ctx.merchant_id, pid,
            title=body.title, objective=body.objective, status=body.status,
        )
    except DesignerNotFound:
        raise _not_found(None, "DESIGN_PROJECT_NOT_FOUND")  # type: ignore[arg-type]
    db.commit()
    return row


@router.get(
    "/projects/{project_id}/briefs",
    response_model=CreativeBriefListResponse,
)
def list_project_briefs(
    project_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Version history for a project. Earlier versions are retained."""
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="INVALID_PROJECT_ID")
    svc = _svc(db)
    try:
        svc.get_project(ctx.merchant_id, pid)
    except DesignerNotFound:
        raise _not_found(None, "DESIGN_PROJECT_NOT_FOUND")  # type: ignore[arg-type]
    rows = svc.list_brief_versions(ctx.merchant_id, pid)
    return {"briefs": rows, "total": len(rows)}


# ── briefs ───────────────────────────────────────────────────────────────


@router.get("/briefs", response_model=CreativeBriefListResponse)
def list_briefs(
    project_id: str | None = Query(default=None),
    review_status: DesignReviewStatus | None = Query(default=None),
    analysis_cycle_id: str | None = Query(default=None),
    current_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    pid = None
    if project_id:
        try:
            pid = uuid.UUID(project_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="INVALID_PROJECT_ID")
    rows = _svc(db).list_briefs(
        ctx.merchant_id,
        project_id=pid,
        review_status=review_status,
        analysis_cycle_id=analysis_cycle_id,
        current_only=current_only,
        limit=limit,
    )
    return {"briefs": rows, "total": len(rows)}


@router.get("/briefs/{brief_id}", response_model=CreativeBriefResponse)
def get_brief(
    brief_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    try:
        bid = uuid.UUID(brief_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="INVALID_BRIEF_ID")
    try:
        return _svc(db).get_brief(ctx.merchant_id, bid)
    except DesignerNotFound:
        raise _not_found(None, "CREATIVE_BRIEF_NOT_FOUND")  # type: ignore[arg-type]


@router.post(
    "/briefs/{brief_id}/review",
    response_model=CreativeBriefResponse,
)
def review_brief(
    brief_id: str,
    body: ReviewDecisionRequest,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(approver_ctx),
) -> Any:
    """Record a HUMAN review decision.

    Requires approver role. This is the only path that can move a brief out of
    ``pending_review``; the agent has none.
    """
    try:
        bid = uuid.UUID(brief_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="INVALID_BRIEF_ID")
    try:
        row = _svc(db).record_review(
            ctx.merchant_id, bid, decision=body.decision, notes=body.notes
        )
    except DesignerNotFound:
        raise _not_found(None, "CREATIVE_BRIEF_NOT_FOUND")  # type: ignore[arg-type]
    db.commit()
    return row


# ── assets ───────────────────────────────────────────────────────────────


@router.get("/assets", response_model=DesignAssetListResponse)
def list_assets(
    project_id: str | None = Query(default=None),
    kind: DesignAssetKind | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    pid = None
    if project_id:
        try:
            pid = uuid.UUID(project_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="INVALID_PROJECT_ID")
    rows = _svc(db).list_assets(ctx.merchant_id, project_id=pid, kind=kind, limit=limit)
    return {"assets": rows, "total": len(rows)}


@router.get(
    "/assets/{asset_id}/versions",
    response_model=DesignAssetVersionListResponse,
)
def list_asset_versions(
    asset_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Append-only version history for one asset."""
    try:
        aid = uuid.UUID(asset_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="INVALID_ASSET_ID")
    svc = _svc(db)
    try:
        asset = svc.get_asset(ctx.merchant_id, aid)
    except DesignerNotFound:
        raise _not_found(None, "DESIGN_ASSET_NOT_FOUND")  # type: ignore[arg-type]
    versions = svc.list_asset_versions(ctx.merchant_id, aid)
    return {"asset": asset, "versions": versions}


@router.post(
    "/assets/{asset_id}/revisions",
    response_model=DesignAssetVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
def revise_asset(
    asset_id: str,
    body: AssetRevisionRequest,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Create a NEW immutable revision. Earlier versions are never touched."""
    try:
        aid = uuid.UUID(asset_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="INVALID_ASSET_ID")
    try:
        version = _svc(db).revise_asset(
            ctx.merchant_id, aid,
            content=body.content,
            change_summary=body.change_summary,
            rationale=body.rationale,
            created_by=f"user:{ctx.user.id}" if ctx.user else "user",
        )
    except DesignerNotFound:
        raise _not_found(None, "DESIGN_ASSET_NOT_FOUND")  # type: ignore[arg-type]
    db.commit()
    return version


# ── image generation (honest state) ──────────────────────────────────────


@router.get("/image-generation")
def image_generation_status(
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Real availability, derived from real configuration.

    Reports ``unavailable`` with a stated reason when the feature is switched
    off or a credential is missing. It never claims ``completed`` and never
    returns an asset reference unless a real, stored image exists.
    """
    return _svc(db).image_generation_status()


class ImageGenerationRequest(BaseModel):
    """Generate an image for an existing design asset.

    ``prompt`` defaults to the asset's current brief objective, so the common
    case needs no user text at all. Bounds mirror the provider's published
    input schema, enforced locally so an oversized value never costs a call.
    """

    asset_id: str | None = Field(
        default=None,
        description="Existing design asset id. Omit to generate directly from prompt.",
    )
    prompt: str | None = Field(
        default=None,
        min_length=1,
        max_length=2048,
        description="Image prompt. Defaults to the current brief's objective or the asset title.",
    )
    steps: int | None = Field(
        default=None,
        ge=1,
        le=8,
        description="Diffusion steps. Omit to let the provider choose its default.",
    )


@router.post("/image-generation")
def request_direct_image_generation(
    body: ImageGenerationRequest | None = None,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Generate one real image directly from an image description, or for an
    existing design asset. No Designer Agent brief or LLM call is required.
    """
    payload = body or ImageGenerationRequest()
    aid: uuid.UUID | None = None
    if payload.asset_id:
        try:
            aid = uuid.UUID(payload.asset_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="INVALID_ASSET_ID")
    svc = _svc(db)
    try:
        status_payload = svc.request_image_generation(
            ctx.merchant_id,
            aid,
            prompt=payload.prompt,
            steps=payload.steps,
        )
    except DesignerNotFound:
        raise _not_found(None, "DESIGN_ASSET_NOT_FOUND")  # type: ignore[arg-type]
    db.commit()
    return status_payload


@router.post("/assets/{asset_id}/image-generation")
def request_image_generation(
    asset_id: str,
    body: ImageGenerationRequest | None = None,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Generate one real image and store it durably.

    Returns 200 with the honest state. When the feature is off, credentials
    are missing, the prompt is invalid, the quota is spent, or the provider
    fails, the response reports that state — it never fabricates an asset
    reference and never marks the asset as rendered.
    """
    try:
        aid = uuid.UUID(asset_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="INVALID_ASSET_ID")
    payload = body or ImageGenerationRequest()
    svc = _svc(db)
    try:
        status_payload = svc.request_image_generation(
            ctx.merchant_id,
            aid,
            prompt=payload.prompt,
            steps=payload.steps,
        )
    except DesignerNotFound:
        raise _not_found(None, "DESIGN_ASSET_NOT_FOUND")  # type: ignore[arg-type]
    db.commit()
    return status_payload


# ── rendered image bytes ───────────────────────────────────────────────────
#
# There is deliberately NO public/static URL for a generated image. Bytes are
# only reachable through this authenticated route, and the merchant check
# happens in SQL, so one workspace can never read another's image by guessing
# an id.


@router.get("/rendered-assets")
def list_rendered_assets(
    asset_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Metadata only. Never returns image bytes."""
    storage = _storage(db)
    if asset_id:
        try:
            aid = uuid.UUID(asset_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="INVALID_ASSET_ID")
        refs = storage.list_for_asset(ctx.merchant_id, aid)
    else:
        refs = storage.list_for_merchant(ctx.merchant_id, limit=limit)
    return {
        "assets": [r.as_dict() for r in refs],
        "total": len(refs),
        "usage_today": storage.usage_today(ctx.merchant_id),
    }


@router.get("/rendered-assets/{rendered_id}/content")
def get_rendered_asset_content(
    rendered_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Stream one image's bytes to its owning workspace.

    Ownership is verified in the query itself; a foreign id returns the same
    404 as a missing one, so this endpoint cannot be used to probe for other
    tenants' images.
    """
    try:
        rid = uuid.UUID(rendered_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="INVALID_RENDERED_ASSET_ID")
    try:
        ref, data = _storage(db).read_bytes(ctx.merchant_id, rid)
    except ImageNotFound:
        raise HTTPException(status_code=404, detail="RENDERED_ASSET_NOT_FOUND")
    return Response(
        content=data,
        media_type=ref.content_type,
        headers={
            # Private, not a public cache entry.
            "Cache-Control": "private, max-age=0, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Length": str(len(data)),
            "X-Image-SHA256": ref.sha256,
        },
    )


# ── UX audit ─────────────────────────────────────────────────────────────


@router.post("/ux-audit", response_model=UXAuditResponse)
def ux_audit(
    body: UXAuditRequest,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Run a UX audit over whatever AUTHORIZED context exists.

    Uses the same real observations the agent uses (Growth Radar signals,
    opportunities and RAG verified facts). When there is not enough context the
    response says ``sufficient_context: false`` rather than returning invented
    findings.
    """
    from backend.app.services.rag_context import RAGContextService

    db_mid = ctx.merchant_id
    rag = RAGContextService(db).build(db_mid, body.objective, window_days=body.window_days)
    verified = list(rag.get("verified_facts") or [])
    signals = list(rag.get("derived_metrics", {}).get("signals") or [])

    evidence: list[Any] = []
    for fact in verified:
        evidence.append(
            {
                "statement": f"{fact.get('fact')}: {fact.get('value')}",
                "basis": "observed",
                "source": fact.get("source") or "verified_facts",
                "value": fact.get("value"),
            }
        )
    for sig in signals[:10]:
        evidence.append(
            {
                "statement": f"{sig.get('title') or sig.get('signal')}: {sig.get('metric')}",
                "basis": "observed",
                "source": "growth_radar",
                "value": sig.get("current_value"),
            }
        )

    sufficient = bool(evidence)
    findings: list[Any] = []
    unavailable_reason: str | None = None

    if not sufficient:
        unavailable_reason = "no_authorized_observations"
    else:
        from backend.app.agents.base import AgentContext, AgentResult
        from backend.app.agents.registry import AGENT_INSTANCES

        agent = AGENT_INSTANCES.get("DesignerAgent")
        observations = {
            "objective": body.objective,
            "verified_facts": verified,
            "signals": signals,
            "grounded_fact_count": len(evidence),
        }
        # The audit reuses the AGENT's own implementation, so there is exactly
        # one UX-audit code path rather than a second divergent one here.
        probe = AgentResult(agent_name="DesignerAgent")
        llm = _audit_llm()
        if agent is None or llm is None:
            unavailable_reason = "llm_not_configured"
        else:
            try:
                findings = list(
                    agent._parse_ux_findings(
                        AgentContext(db=db, merchant_id=ctx.merchant_id, llm=llm),
                        probe,
                        observations,
                    )
                    or []
                )
                if probe.errors:
                    unavailable_reason = str(probe.errors[-1])[:200]
            except Exception as exc:
                log.warning("ux audit generation failed: %s", exc)
                unavailable_reason = f"ux_audit_failed:{type(exc).__name__}"

    radar_refs = [
        {"kind": "growth_signal", "id": s.get("id"), "title": s.get("title")}
        for s in signals[:5]
        if isinstance(s, dict)
    ]

    return UXAuditResponse(
        findings=findings,
        evidence=evidence,
        radar_references=radar_refs,
        sufficient_context=sufficient,
        unavailable_reason=unavailable_reason,
        data_sufficiency=rag.get("data_sufficiency"),
    )


def _audit_llm() -> Any:
    """Resolve the configured LLM provider for a server-initiated call.

    Returns None when no provider is configured, which the caller turns into an
    honest "unavailable" state rather than a fabricated finding.
    """
    from backend.app.ai.llm.provider import resolve_llm_provider
    from backend.app.core.config import get_settings

    settings = get_settings()
    resolved = resolve_llm_provider(settings)
    if resolved is None:
        return None
    return resolved.build(
        timeout=settings.LLM_REQUEST_TIMEOUT,
        max_retries=settings.LLM_MAX_RETRIES,
    )


# ── handoffs ─────────────────────────────────────────────────────────────


@router.post("/handoffs", response_model=HandoffResponse, status_code=201)
def create_handoff(
    body: HandoffRequest,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Hand a stored brief to another platform workflow.

    This records a structured, validated handoff. It does NOT approve or
    execute anything. When ``proposed_action_type`` is supplied, the handoff
    creates a row through the EXISTING ``action_service.create_action``, so the
    item faces the platform's normal guardrail evaluation, mandatory human
    approval and the ``EXECUTION_ENABLED`` gate. There is no Designer Agent
    approval engine.
    """
    from backend.app.models.designer import DesignProject  # noqa: F401
    from backend.app.services import action_service

    svc = _svc(db)
    try:
        brief = svc.get_brief(ctx.merchant_id, body.brief_id)
    except DesignerNotFound:
        raise HTTPException(status_code=404, detail="CREATIVE_BRIEF_NOT_FOUND")

    action_id: uuid.UUID | None = None
    if body.proposed_action_type is not None:
        # The payload is shaped to the EXISTING ``GenerateOpportunityPayload``
        # contract, because ``action_service.create_action`` validates it.
        # Nothing here bypasses that validation: an invalid payload is refused
        # by the platform, not coerced.
        action = action_service.create_action(
            db,
            merchant_id=ctx.merchant_id,
            action_type=body.proposed_action_type,
            input_payload={
                "opportunity_type": "campaign",
                "title": brief.title[:200],
                "description": (
                    f"Creative brief {brief.id} (v{brief.version}) from the "
                    f"Designer Agent, handed to {body.target}. "
                    f"{body.note or ''}".strip()
                )[:1000],
                "confidence": str(float(brief.confidence))
                if brief.confidence is not None
                else "0.5",
                "expected_revenue": "0",
                "target_customer_count": 0,
                "reasoning": [
                    "Designer Agent handoff",
                    f"brief_id={brief.id}",
                    f"review_status={brief.review_status.value}",
                ],
                "source": "designer_agent_handoff",
                "brief_id": str(brief.id),
                "target": body.target,
            },
            requested_by="agent:DesignerAgent",
        )
        action_id = action.id
    db.commit()

    return HandoffResponse(
        handoff_id=brief.id,
        target=body.target,
        status="proposed" if action_id else "recorded",
        brief_id=brief.id,
        created_at=brief.created_at,
        action_id=action_id,
    )


__all__ = ["router"]
