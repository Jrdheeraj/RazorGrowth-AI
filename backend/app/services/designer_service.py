"""Designer workspace service — persistence, versioning and validation.

This is the only module that writes design records. The agent asks it to store
an output; it decides whether that output is actually storable and in what
shape.

WHAT MAKES AN OUTPUT STORABLE
-----------------------------
Before an agent run is recorded as successful, the brief is validated:

  * it parses against the structured schema (the model did not return prose);
  * it carries at least one ``observed`` or ``derived`` evidence statement —
    a brief built only from hypotheses is refused rather than stored;
  * no field claims a measured business outcome;
  * the declared asset kind matches what the agent actually produced, so a
    text brief is never filed as a rendered image.

A validation failure is a FAILURE of the run, recorded with its reason. It is
never downgraded to "completed with warnings".

VERSIONING
----------
``creative_briefs`` and ``design_asset_versions`` are append-only. ``revise_*``
writes a new row with an incremented version and flips the previous row's
``is_current`` flag; it never updates or deletes the prior content, so what a
merchant approved against cannot change underneath them.

IMAGE GENERATION
----------------
One provider is configured: Cloudflare Workers AI
(``@cf/black-forest-labs/flux-1-schnell``), reached only through
``CloudflareImageGenerator``. It is gated by ``IMAGE_GENERATION_ENABLED`` plus
a real account id and token; when any of those is missing
``image_generation_status()`` reports ``unavailable`` with the reason, and no
code path fabricates a ``DesignAssetKind.rendered_image`` row, a fake URL, or a
placeholder presented as a generated creative.

Image generation does NOT require a creative brief. ``request_image_generation``
accepts a user-supplied image description directly, so a workspace whose LLM
provider is unavailable can still render real images. Two callers exist and are
deliberately distinct:

  * the Designer Agent, which renders from a brief it already persisted
    (LLM-assisted), and
  * the API route, which renders from a plain description with no LLM call at
    all (direct generation).

Neither one reports a brief it did not produce.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from backend.app.models.agent_debate import AgentDebate
from backend.app.models.agent_run import AgentRun
from backend.app.models.designer import (
    IMAGE_GENERATION_UNAVAILABLE,
    CreativeBrief,
    DesignAsset,
    DesignAssetVersion,
    DesignProject,
)
from backend.app.core.config import get_settings
from backend.app.integrations.cloudflare_image import (
    MODEL_LABEL,
    PROVIDER_NAME,
    CloudflareImageGenerator,
    ImageGenerationError,
    provider_availability,
    validate_prompt,
    validate_steps,
)
from backend.app.models.enums import (
    AgentRunStatus,
    DesignAssetKind,
    DesignAssetStatus,
    DesignProjectStatus,
    DesignReviewStatus,
    ImageGenerationStatus,
)
from backend.app.models.growth_signal import GrowthSignal
from backend.app.models.opportunity import GrowthOpportunity
from backend.app.services.design_asset_storage import (
    DesignAssetStorage,
    ImageQuotaExceeded,
    ImageStorageConflict,
    ImageValidationError,
)
from backend.app.schemas.designer import (
    ColorGuidance,
    CreativeBriefSpec,
    DesignVariant,
    Evidence,
    UXFinding,
)

log = logging.getLogger(__name__)


class DesignerValidationError(ValueError):
    """An agent output that must not be persisted."""

    def __init__(self, reason: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


class DesignerNotFound(LookupError):
    """A design record that is absent, or belongs to another merchant."""


#: Outcomes an agent output may NOT claim. A design change that has not shipped
#: cannot have a measured effect, so any of these appearing in a brief is a
#: fabrication, not a forecast.
_FORBIDDEN_CLAIM_MARKERS = (
    "will increase conversion",
    "will increase revenue",
    "guaranteed",
    "proven to increase",
    "increases conversion by",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json(value: Any) -> Any:
    """JSON-safe projection of a Pydantic model / dict."""
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value


def _num(value: float | None) -> float | None:
    return float(value) if value is not None else None


# ══════════════════════════════════════════════════════════════════════════
# Validation
# ══════════════════════════════════════════════════════════════════════════


def validate_brief(spec: CreativeBriefSpec) -> dict[str, Any]:
    """Validate a parsed brief. Returns a report; raises on refusal.

    The report is stored on the brief row so a reviewer can see exactly what
    the agent checked and why, instead of trusting a green badge.
    """
    grounded = [e for e in spec.evidence if e.basis in ("observed", "derived")]
    if not grounded:
        raise DesignerValidationError(
            "INSUFFICIENT_EVIDENCE",
            {
                "reason": (
                    "The brief contains no observed or derived evidence "
                    "statement, so it cannot be stored as real creative work."
                ),
                "evidence_count": len(spec.evidence),
            },
        )

    haystack = " ".join(
        [spec.objective, spec.layout_direction or "", spec.typography_guidance or ""]
        + list(spec.content_requirements)
        + list(spec.brand_constraints)
    ).lower()
    claims = [m for m in _FORBIDDEN_CLAIM_MARKERS if m in haystack]
    if claims:
        raise DesignerValidationError(
            "UNSUPPORTED_OUTCOME_CLAIM",
            {
                "reason": (
                    "The brief claims a measured business outcome. A design "
                    "change that has not shipped has no measured effect."
                ),
                "markers": claims,
            },
        )

    missing_required = []
    if not spec.audience:
        missing_required.append("audience")
    if not spec.channel:
        missing_required.append("channel")
    if not spec.layout_direction:
        missing_required.append("layout_direction")

    warnings: list[str] = []
    if spec.color_guidance and not spec.color_guidance.palette:
        warnings.append("color_guidance_present_without_palette")
    if not spec.variants:
        warnings.append("no_variants_proposed")
    if not spec.accessibility_considerations:
        warnings.append("no_accessibility_considerations")
    for v in spec.variants:
        if not v.evidence_refs:
            warnings.append(f"variant_without_evidence_refs:{v.variant_key}")

    return {
        "valid": True,
        "grounded_evidence_count": len(grounded),
        "hypothesis_count": sum(
            1 for e in spec.evidence if e.basis == "hypothesis"
        ),
        "unknown_count": sum(1 for e in spec.evidence if e.basis == "unknown"),
        "variant_count": len(spec.variants),
        "ux_finding_count": len(spec.ux_findings),
        "missing_required": missing_required,
        "warnings": warnings,
        "checked_at": _utcnow().isoformat(),
    }


# ══════════════════════════════════════════════════════════════════════════
# Service
# ══════════════════════════════════════════════════════════════════════════


class DesignerService:
    """Persistence and read model for the Designer workspace."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── projects ──────────────────────────────────────────────────────────

    def create_project(
        self,
        merchant_id: uuid.UUID,
        *,
        objective: str,
        title: str | None = None,
        project_type: str = "campaign_creative",
        analysis_cycle_id: str | None = None,
        debate_id: uuid.UUID | None = None,
        signal: GrowthSignal | None = None,
        opportunity: GrowthOpportunity | None = None,
    ) -> DesignProject:
        project = DesignProject(
            merchant_id=merchant_id,
            title=(title or objective.strip()[:200])[:255],
            objective=objective.strip(),
            project_type=project_type[:60],
            status=DesignProjectStatus.active,
            analysis_cycle_id=analysis_cycle_id,
            debate_id=debate_id,
            source_signal_type=(signal.signal_type if signal else None),
            source_signal_id=(str(signal.id) if signal else None),
            source_opportunity_id=(opportunity.id if opportunity else None),
        )
        self.db.add(project)
        self.db.flush()
        return project

    def get_project(
        self, merchant_id: uuid.UUID, project_id: uuid.UUID
    ) -> DesignProject:
        row = self.db.scalar(
            select(DesignProject).where(
                DesignProject.id == project_id,
                DesignProject.merchant_id == merchant_id,
            )
        )
        if row is None:
            raise DesignerNotFound(f"DESIGN_PROJECT_NOT_FOUND:{project_id}")
        return row

    def list_projects(
        self,
        merchant_id: uuid.UUID,
        *,
        status: DesignProjectStatus | None = None,
        project_type: str | None = None,
        analysis_cycle_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DesignProject]:
        stmt = select(DesignProject).where(DesignProject.merchant_id == merchant_id)
        if status is not None:
            stmt = stmt.where(DesignProject.status == status)
        if project_type:
            stmt = stmt.where(DesignProject.project_type == project_type)
        if analysis_cycle_id:
            stmt = stmt.where(DesignProject.analysis_cycle_id == analysis_cycle_id)
        stmt = (
            stmt.order_by(DesignProject.created_at.desc(), DesignProject.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.scalars(stmt).all())

    def count_projects(self, merchant_id: uuid.UUID) -> int:
        return int(
            self.db.scalar(
                select(func.count())
                .select_from(DesignProject)
                .where(DesignProject.merchant_id == merchant_id)
            )
            or 0
        )

    def update_project(
        self,
        merchant_id: uuid.UUID,
        project_id: uuid.UUID,
        *,
        title: str | None = None,
        objective: str | None = None,
        status: DesignProjectStatus | None = None,
    ) -> DesignProject:
        project = self.get_project(merchant_id, project_id)
        if title is not None:
            project.title = title[:255]
        if objective is not None:
            project.objective = objective.strip()
        if status is not None:
            project.status = status
        self.db.flush()
        return project

    def find_project_by_objective(
        self, merchant_id: uuid.UUID, objective: str, *, window_hours: int = 24
    ) -> DesignProject | None:
        """Idempotency guard for a repeated design request.

        Submitting the same objective twice within the window returns the
        existing project instead of creating a second one, so a double-clicked
        button cannot fork a design thread.
        """
        since = _utcnow() - timedelta(hours=window_hours)
        row = self.db.scalars(
            select(DesignProject)
            .where(
                DesignProject.merchant_id == merchant_id,
                DesignProject.objective == objective.strip(),
                DesignProject.created_at >= since,
            )
            .order_by(DesignProject.created_at.desc())
            .limit(1)
        ).first()
        return row

    # ── briefs ────────────────────────────────────────────────────────────

    def store_brief(
        self,
        merchant_id: uuid.UUID,
        project: DesignProject,
        spec: CreativeBriefSpec,
        *,
        review_status: DesignReviewStatus = DesignReviewStatus.pending_review,
        analysis_cycle_id: str | None = None,
        agent_run_id: uuid.UUID | None = None,
        llm_provider: str | None = None,
        llm_model: str | None = None,
        radar_references: list[dict[str, Any]] | None = None,
        ux_findings: list[UXFinding] | None = None,
    ) -> CreativeBrief:
        """Validate and persist a brief as the project's newest version."""
        report = validate_brief(spec)

        version = self._next_brief_version(merchant_id, project.id)
        # Previous versions are RETAINED; only the pointer moves. This is an
        # UPDATE (not a select-then-mutate) so it stays a single statement.
        self.db.execute(
            update(CreativeBrief)
            .where(
                CreativeBrief.project_id == project.id,
                CreativeBrief.merchant_id == merchant_id,
                CreativeBrief.is_current == 1,
            )
            .values(is_current=0)
        )

        brief = CreativeBrief(
            merchant_id=merchant_id,
            project_id=project.id,
            version=version,
            is_current=1,
            title=spec.title[:255],
            objective=spec.objective,
            audience=spec.audience,
            channel=spec.channel,
            format_spec=spec.format_spec,
            brand_constraints=list(spec.brand_constraints) or None,
            content_requirements=list(spec.content_requirements) or None,
            layout_direction=spec.layout_direction,
            color_guidance=(
                ", ".join(spec.color_guidance.palette)
                if spec.color_guidance and spec.color_guidance.palette
                else None
            ),
            typography_guidance=spec.typography_guidance,
            accessibility_considerations=list(spec.accessibility_considerations) or None,
            dependencies=list(spec.dependencies) or None,
            open_questions=list(spec.open_questions) or None,
            assumptions=list(spec.assumptions) or None,
            evidence=[e.model_dump() for e in spec.evidence] or None,
            radar_references=radar_references or None,
            variants=[v.model_dump() for v in spec.variants] or None,
            review_status=review_status,
            confidence=Decimal(str(spec.confidence)) if spec.confidence is not None else None,
            validation={**report, "ux_findings": [f.model_dump() for f in (ux_findings or spec.ux_findings)] or None},
            llm_provider=llm_provider,
            llm_model=llm_model,
            analysis_cycle_id=analysis_cycle_id or project.analysis_cycle_id,
            agent_run_id=agent_run_id,
        )
        self.db.add(brief)
        self.db.flush()

        # One asset row per distinct variant so a variant is a first-class,
        # reviewable object rather than a field inside the brief JSON. The
        # title uses a plain colon: an em dash renders as mojibake in
        # terminals/logs that are not UTF-8.
        for variant in spec.variants:
            self.add_asset(
                merchant_id,
                project,
                kind=DesignAssetKind.variant,
                title=f"{spec.title}: {variant.title}"[:255],
                variant_key=variant.variant_key[:80],
                content=variant.model_dump(),
                brief_id=brief.id,
                rationale=variant.rationale,
                change_summary="Initial variant",
            )
        return brief

    def _next_brief_version(self, merchant_id: uuid.UUID, project_id: uuid.UUID) -> int:
        current = self.db.scalar(
            select(func.max(CreativeBrief.version)).where(
                CreativeBrief.project_id == project_id,
                CreativeBrief.merchant_id == merchant_id,
            )
        )
        return int(current or 0) + 1

    def get_brief(
        self, merchant_id: uuid.UUID, brief_id: uuid.UUID
    ) -> CreativeBrief:
        row = self.db.scalar(
            select(CreativeBrief).where(
                CreativeBrief.id == brief_id,
                CreativeBrief.merchant_id == merchant_id,
            )
        )
        if row is None:
            raise DesignerNotFound(f"CREATIVE_BRIEF_NOT_FOUND:{brief_id}")
        return row

    def get_current_brief(
        self, merchant_id: uuid.UUID, project_id: uuid.UUID
    ) -> CreativeBrief | None:
        return self.db.scalar(
            select(CreativeBrief)
            .where(
                CreativeBrief.project_id == project_id,
                CreativeBrief.merchant_id == merchant_id,
                CreativeBrief.is_current == 1,
            )
            .order_by(CreativeBrief.version.desc())
            .limit(1)
        )

    def list_briefs(
        self,
        merchant_id: uuid.UUID,
        *,
        project_id: uuid.UUID | None = None,
        review_status: DesignReviewStatus | None = None,
        analysis_cycle_id: str | None = None,
        current_only: bool = False,
        limit: int = 50,
    ) -> list[CreativeBrief]:
        stmt = select(CreativeBrief).where(
            CreativeBrief.merchant_id == merchant_id
        )
        if project_id is not None:
            stmt = stmt.where(CreativeBrief.project_id == project_id)
        if review_status is not None:
            stmt = stmt.where(CreativeBrief.review_status == review_status)
        if analysis_cycle_id:
            stmt = stmt.where(CreativeBrief.analysis_cycle_id == analysis_cycle_id)
        if current_only:
            stmt = stmt.where(CreativeBrief.is_current == 1)
        stmt = stmt.order_by(CreativeBrief.created_at.desc()).limit(limit)
        return list(self.db.scalars(stmt).all())

    def list_brief_versions(
        self, merchant_id: uuid.UUID, project_id: uuid.UUID
    ) -> list[CreativeBrief]:
        return list(
            self.db.scalars(
                select(CreativeBrief)
                .where(
                    CreativeBrief.project_id == project_id,
                    CreativeBrief.merchant_id == merchant_id,
                )
                .order_by(CreativeBrief.version.desc())
            ).all()
        )

    def record_review(
        self,
        merchant_id: uuid.UUID,
        brief_id: uuid.UUID,
        *,
        decision: str,
        notes: str | None = None,
    ) -> CreativeBrief:
        """Record a HUMAN review decision on a brief.

        Called only from an authenticated, role-guarded route. The agent has no
        path to this method, so it can prepare work but never approve it.
        """
        brief = self.get_brief(merchant_id, brief_id)
        brief.review_status = DesignReviewStatus(decision)
        brief.review_notes = notes
        self.db.flush()
        return brief

    # ── assets & versions ─────────────────────────────────────────────────

    def add_asset(
        self,
        merchant_id: uuid.UUID,
        project: DesignProject,
        *,
        kind: DesignAssetKind,
        title: str,
        content: dict[str, Any],
        brief_id: uuid.UUID | None = None,
        variant_key: str | None = None,
        rationale: str | None = None,
        change_summary: str | None = "Initial version",
        evidence: list[Any] | None = None,
    ) -> DesignAsset:
        asset = DesignAsset(
            merchant_id=merchant_id,
            project_id=project.id,
            brief_id=brief_id,
            kind=kind,
            title=title[:255],
            variant_key=variant_key,
            status=DesignAssetStatus.ready_for_review,
            review_status=DesignReviewStatus.pending_review,
            version_count=1,
            # Honest state for a text-only asset. Derived from real
            # configuration rather than hard-coded, so a workspace with
            # generation enabled is not told "unavailable" on every asset.
            # `asset_reference` stays None because no image exists yet — this
            # is never a claim that one does.
            image_generation=self.image_generation_status(),
        )
        self.db.add(asset)
        self.db.flush()

        version = DesignAssetVersion(
            merchant_id=merchant_id,
            asset_id=asset.id,
            version=1,
            content=content,
            rationale=rationale,
            change_summary=change_summary,
            evidence=evidence,
            created_by="agent:DesignerAgent",
        )
        self.db.add(version)
        self.db.flush()

        asset.current_version_id = version.id
        self.db.flush()
        return asset

    def revise_asset(
        self,
        merchant_id: uuid.UUID,
        asset_id: uuid.UUID,
        *,
        content: dict[str, Any],
        change_summary: str,
        rationale: str | None = None,
        created_by: str = "agent:DesignerAgent",
    ) -> DesignAssetVersion:
        """Append a NEW immutable revision. History is never rewritten."""
        asset = self.get_asset(merchant_id, asset_id)
        version_no = self._next_asset_version(asset)
        version = DesignAssetVersion(
            merchant_id=merchant_id,
            asset_id=asset.id,
            version=version_no,
            content=content,
            rationale=rationale,
            change_summary=change_summary,
            created_by=created_by,
        )
        self.db.add(version)
        asset.version_count = version_no
        asset.current_version_id = version.id
        self.db.flush()
        return version

    def _next_asset_version(self, asset: DesignAsset) -> int:
        current = self.db.scalar(
            select(func.max(DesignAssetVersion.version)).where(
                DesignAssetVersion.asset_id == asset.id
            )
        )
        return int(current or 0) + 1

    def get_asset(self, merchant_id: uuid.UUID, asset_id: uuid.UUID) -> DesignAsset:
        row = self.db.scalar(
            select(DesignAsset).where(
                DesignAsset.id == asset_id,
                DesignAsset.merchant_id == merchant_id,
            )
        )
        if row is None:
            raise DesignerNotFound(f"DESIGN_ASSET_NOT_FOUND:{asset_id}")
        return row

    def list_assets(
        self,
        merchant_id: uuid.UUID,
        *,
        project_id: uuid.UUID | None = None,
        kind: DesignAssetKind | None = None,
        limit: int = 50,
    ) -> list[DesignAsset]:
        stmt = select(DesignAsset).where(DesignAsset.merchant_id == merchant_id)
        if project_id is not None:
            stmt = stmt.where(DesignAsset.project_id == project_id)
        if kind is not None:
            stmt = stmt.where(DesignAsset.kind == kind)
        stmt = stmt.order_by(DesignAsset.created_at.desc()).limit(limit)
        return list(self.db.scalars(stmt).all())

    def list_asset_versions(
        self, merchant_id: uuid.UUID, asset_id: uuid.UUID
    ) -> list[DesignAssetVersion]:
        self.get_asset(merchant_id, asset_id)  # tenant check
        return list(
            self.db.scalars(
                select(DesignAssetVersion)
                .where(
                    DesignAssetVersion.asset_id == asset_id,
                    DesignAssetVersion.merchant_id == merchant_id,
                )
                .order_by(DesignAssetVersion.version.desc())
            ).all()
        )

    def current_asset_content(
        self, merchant_id: uuid.UUID, asset: DesignAsset
    ) -> dict[str, Any]:
        if asset.current_version_id is None:
            return {}
        row = self.db.scalar(
            select(DesignAssetVersion).where(
                DesignAssetVersion.id == asset.current_version_id,
                DesignAssetVersion.merchant_id == merchant_id,
            )
        )
        return dict(row.content) if row is not None else {}

    # ── image generation ──────────────────────────────────────────────────
    #
    # Provider bytes live in DesignAssetStorage, never in this service's rows,
    # so ``design_assets`` / ``design_asset_versions`` stay byte-free and
    # append-only. This section decides WHETHER and WHAT; the storage module
    # decides HOW the bytes are kept.

    def image_generation_status(self) -> dict[str, Any]:
        """Real availability from real configuration.

        Returns ``unavailable`` with a stated reason whenever the flag is off
        or a credential is missing. It never reports ``completed`` without a
        stored image, and never invents an asset reference.
        """
        settings = get_settings()
        availability = provider_availability(
            enabled=bool(settings.IMAGE_GENERATION_ENABLED),
            account_id=settings.CLOUDFLARE_ACCOUNT_ID,
            api_token=settings.CLOUDFLARE_API_TOKEN,
        )
        if not availability.available:
            return {
                "status": ImageGenerationStatus.unavailable.value,
                "provider": PROVIDER_NAME,
                "reason": availability.reason,
                "asset_reference": None,
                "model": MODEL_LABEL,
            }
        return {
            "status": "available",
            "provider": availability.provider,
            "reason": None,
            "asset_reference": None,
            "model": MODEL_LABEL,
        }

    def _storage(self) -> DesignAssetStorage:
        settings = get_settings()
        return DesignAssetStorage(
            self.db,
            max_bytes=settings.IMAGE_MAX_BYTES,
            daily_quota=settings.IMAGE_DAILY_QUOTA_PER_MERCHANT,
            daily_storage_quota_bytes=settings.IMAGE_DAILY_STORAGE_QUOTA_BYTES,
            max_pixels=settings.IMAGE_MAX_PIXELS,
            max_width=settings.IMAGE_MAX_WIDTH,
            max_height=settings.IMAGE_MAX_HEIGHT,
        )

    def request_image_generation(
        self,
        merchant_id: uuid.UUID,
        asset_id: uuid.UUID | None = None,
        *,
        prompt: str | None = None,
        steps: int | None = None,
        generator: Any | None = None,
    ) -> dict[str, Any]:
        """Generate and durably store one real image for a design asset.

        ORDER IS THE POINT
        ------------------
            1. capability check  — off / no credentials => honest refusal
            2. tenant check      — the asset must belong to THIS merchant
            3. validate prompt   — before any provider spend
            4. generate          — the only externally billed step
            5. create version    — so bytes always have a version to belong to
            6. validate + store bytes
            7. mark the asset rendered, move it to review
            8. commit            — bytes and metadata land together

        Any failure before the commit leaves no asset state change and no
        image row, so there is never a stored "creative" without real bytes,
        and never an orphan byte blob.

        A regenerated image becomes a NEW asset version, preserving
        append-only semantics rather than overwriting the previous image.
        """
        if asset_id is not None:
            asset = self.get_asset(merchant_id, asset_id)  # tenant check first
        else:
            asset = None
        settings = get_settings()

        availability = provider_availability(
            enabled=bool(settings.IMAGE_GENERATION_ENABLED),
            account_id=settings.CLOUDFLARE_ACCOUNT_ID,
            api_token=settings.CLOUDFLARE_API_TOKEN,
        )
        if not availability.available:
            # Never fabricated, never silently substituted.
            return self.image_generation_status()

        # Direct image generation (no existing design asset): accept the
        # user-supplied description by itself. No LLM / Designer Agent run
        # is involved; this creates only an owning asset so the bytes can be
        # persisted through the existing version + storage system.
        if asset is None:
            if not (prompt and str(prompt).strip()):
                return {
                    "status": "failed",
                    "provider": PROVIDER_NAME,
                    "model": MODEL_LABEL,
                    "reason": "An image description is required for direct image generation.",
                    "code": "INVALID_PROMPT",
                    "asset_reference": None,
                }
            try:
                clean_prompt = validate_prompt(str(prompt))
            except ValueError as exc:
                return {
                    "status": "failed",
                    "provider": PROVIDER_NAME,
                    "model": MODEL_LABEL,
                    "reason": "The image prompt is invalid.",
                    "code": "INVALID_PROMPT",
                    "detail": str(exc),
                    "asset_reference": None,
                }
            project = self.find_project_by_objective(merchant_id, clean_prompt)
            if project is None:
                project = self.create_project(
                    merchant_id,
                    objective=clean_prompt,
                    title=clean_prompt,
                    project_type="image_generation",
                )
            asset = DesignAsset(
                merchant_id=merchant_id,
                project_id=project.id,
                kind=DesignAssetKind.rendered_image,
                title=clean_prompt[:255],
                status=DesignAssetStatus.draft,
                review_status=DesignReviewStatus.draft,
                version_count=0,
                current_version_id=None,
                image_generation=self.image_generation_status(),
            )
            self.db.add(asset)
            self.db.flush()
            asset_id = asset.id

        source_prompt = prompt
        if not source_prompt:
            if asset_id is not None:
                current = self.get_current_brief(merchant_id, asset.project_id)
                source_prompt = current.objective if current else asset.title
            else:
                source_prompt = asset.title

        try:
            source_prompt = validate_prompt(source_prompt)
            steps = validate_steps(steps)
        except ValueError as exc:
            # Operator input problem, not a provider problem. No spend.
            return self._set_image_state(
                asset,
                status="failed",
                reason="The image prompt is invalid.",
                code="INVALID_PROMPT",
                detail=str(exc),
            )

        client = generator
        owns_client = client is None
        if client is None:
            client = CloudflareImageGenerator(
                account_id=settings.CLOUDFLARE_ACCOUNT_ID,
                api_token=settings.CLOUDFLARE_API_TOKEN,
                timeout_seconds=settings.IMAGE_REQUEST_TIMEOUT_SECONDS,
                max_retries=settings.IMAGE_MAX_RETRIES,
                max_bytes=settings.IMAGE_MAX_BYTES,
            )

        try:
            image = client.generate(source_prompt, steps=steps)
        except ImageGenerationError as exc:
            log.warning(
                "designer image generation failed (asset=%s, code=%s)",
                asset_id,
                exc.code,
            )
            return self._set_image_state(
                asset,
                status="failed",
                reason=exc.safe_message,
                code=exc.code,
            )
        finally:
            if owns_client:
                client.close()

        try:
            # Steps 5 and 6 run inside a SAVEPOINT, for two reasons.
            #
            #  * The version row and the image row must land or vanish
            #    together. A version stamped ``rendered: True`` whose bytes
            #    were refused would be a creative the merchant never received.
            #
            #  * A refusal here must not discard work the caller had already
            #    stored. The Designer Agent renders an image from a brief it
            #    has just persisted, and a quota refusal must never cost that
            #    merchant their brief. Rolling back the innermost transaction
            #    covers both callers: the savepoint when one is open, and the
            #    whole request transaction otherwise.
            with self.db.begin_nested():
                # 5. A new version, so a regeneration never overwrites history.
                version = self.revise_asset(
                    merchant_id,
                    asset_id,
                    content={
                        "kind": asset.kind.value,
                        "title": asset.title,
                        "rendered": True,
                        "provider": image.provider,
                        "model": image.model,
                        "steps": image.steps,
                    },
                    change_summary=(
                        "Rendered image generated"
                        if asset.version_count <= 1
                        else "Image re-generated"
                    ),
                    rationale="Image generated by the configured image provider.",
                    created_by="agent:DesignerAgent",
                )
                # 6. Validate + persist. Raises on a non-JPEG or oversize
                #    payload, which unwinds the savepoint.
                stored = self._storage().store(
                    merchant_id,
                    asset_id=asset_id,
                    version_id=version.id,
                    data=image.data,
                    provider=image.provider,
                    model=image.model,
                    steps=image.steps,
                    created_by="agent:DesignerAgent",
                )
        except ImageQuotaExceeded:
            # The workspace is out of images for today. Reporting ``available``
            # here would be a lie: nothing was generated and nothing stored.
            log.warning("designer image quota exhausted (asset=%s)", asset_id)
            return self._set_image_state(
                asset,
                status="failed",
                reason="This workspace has used its image quota for today.",
                code="IMAGE_QUOTA_EXCEEDED",
            )
        except (ImageValidationError, ImageStorageConflict) as exc:
            log.warning(
                "designer image persistence refused (asset=%s): %s",
                asset_id,
                type(exc).__name__,
            )
            return self._set_image_state(
                asset,
                status="failed",
                reason="The generated image failed validation and was not stored.",
                code="IMAGE_PERSIST_REFUSED",
            )

        # 7. Honest success: only now, with validated + stored bytes.
        asset.kind = DesignAssetKind.rendered_image
        asset.status = DesignAssetStatus.ready_for_review
        # A generated image is work for a human to accept, never auto-approved.
        asset.review_status = DesignReviewStatus.pending_review
        asset.image_generation = {
            "status": ImageGenerationStatus.completed.value,
            "provider": image.provider,
            "model": image.model,
            "steps": image.steps,
            "reason": None,
            "asset_reference": str(stored.id),
            "rendered_asset_id": str(stored.id),
            "content_type": stored.content_type,
            "byte_size": stored.byte_size,
            "width": stored.width,
            "height": stored.height,
            "sha256": stored.sha256,
            "version_id": str(stored.version_id),
        }
        self.db.flush()
        return dict(asset.image_generation)

    def _set_image_state(
        self,
        asset: DesignAsset,
        *,
        status: str,
        reason: str,
        code: str,
        detail: str | None = None,
    ) -> dict[str, Any]:
        """Record a real failure on the asset. Never a fake success."""
        state = {
            "status": status,
            "provider": PROVIDER_NAME,
            "model": MODEL_LABEL,
            "reason": reason,
            "code": code,
            # The prompt is NEVER stored here — it is merchant content and may
            # be sensitive.
            "asset_reference": None,
        }
        if detail:
            # Only our own validation text, never provider output.
            state["detail"] = detail
        asset.image_generation = state
        self.db.flush()
        return state

    # ── dashboard read model ──────────────────────────────────────────────

    def metrics(self, merchant_id: uuid.UUID) -> list[dict[str, Any]]:
        """Every metric derived from persisted rows. No invented trend."""
        now = _utcnow()
        week_ago = now - timedelta(days=7)

        projects = self.count_projects(merchant_id)
        briefs_total = int(
            self.db.scalar(
                select(func.count())
                .select_from(CreativeBrief)
                .where(CreativeBrief.merchant_id == merchant_id)
            )
            or 0
        )
        awaiting_review = int(
            self.db.scalar(
                select(func.count())
                .select_from(CreativeBrief)
                .where(
                    CreativeBrief.merchant_id == merchant_id,
                    CreativeBrief.review_status
                    == DesignReviewStatus.pending_review,
                )
            )
            or 0
        )
        approved = int(
            self.db.scalar(
                select(func.count())
                .select_from(CreativeBrief)
                .where(
                    CreativeBrief.merchant_id == merchant_id,
                    CreativeBrief.review_status == DesignReviewStatus.approved,
                )
            )
            or 0
        )
        this_week = int(
            self.db.scalar(
                select(func.count())
                .select_from(DesignProject)
                .where(
                    DesignProject.merchant_id == merchant_id,
                    DesignProject.created_at >= week_ago,
                )
            )
            or 0
        )
        failed_runs = int(
            self.db.scalar(
                select(func.count())
                .select_from(AgentRun)
                .where(
                    AgentRun.merchant_id == merchant_id,
                    AgentRun.agent_name == "DesignerAgent",
                    AgentRun.status == AgentRunStatus.failed,
                )
            )
            or 0
        )
        assets = int(
            self.db.scalar(
                select(func.count())
                .select_from(DesignAsset)
                .where(DesignAsset.merchant_id == merchant_id)
            )
            or 0
        )

        return [
            {
                "key": "projects",
                "label": "Design projects",
                "value": projects,
                "hint": (
                    f"{this_week} created in the last 7 days"
                    if projects
                    else "No projects yet"
                ),
            },
            {
                "key": "briefs",
                "label": "Creative briefs",
                "value": briefs_total,
                "hint": (
                    f"{assets} versioned assets"
                    if briefs_total
                    else "No briefs generated yet"
                ),
            },
            {
                "key": "awaiting_review",
                "label": "Awaiting your review",
                "value": awaiting_review,
                "hint": (
                    "Nothing is executed until you approve it"
                    if awaiting_review
                    else "Nothing waiting on you"
                ),
            },
            {
                "key": "approved",
                "label": "Approved briefs",
                "value": approved,
                "hint": "Approved by you" if approved else "No approvals yet",
            },
            {
                "key": "failed_runs",
                "label": "Failed agent runs",
                "value": failed_runs,
                "hint": (
                    "The most recent error is in Recent Activity"
                    if failed_runs
                    else "No failed Designer Agent run"
                ),
            },
        ]

    def activity(
        self, merchant_id: uuid.UUID, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Genuine persisted events only — never synthesised timestamps."""
        items: list[dict[str, Any]] = []

        for b in self.list_briefs(merchant_id, limit=limit):
            items.append(
                {
                    "id": f"brief-{b.id}",
                    "kind": "brief",
                    "title": b.title,
                    "detail": (
                        f"{b.validation.get('variant_count', 0)} variants"
                        if b.validation
                        else None
                    ),
                    "status": b.review_status.value,
                    "at": b.created_at,
                }
            )
        for p in self.list_projects(merchant_id, limit=limit):
            items.append(
                {
                    "id": f"project-{p.id}",
                    "kind": "project",
                    "title": p.title,
                    "detail": p.project_type.replace("_", " "),
                    "status": p.status.value,
                    "at": p.created_at,
                }
            )
        runs = list(
            self.db.scalars(
                select(AgentRun)
                .where(
                    AgentRun.merchant_id == merchant_id,
                    AgentRun.agent_name == "DesignerAgent",
                )
                .order_by(AgentRun.started_at.desc())
                .limit(limit)
            ).all()
        )
        for r in runs:
            detail = None
            if r.errors:
                detail = str(r.errors[0])[:160]
            elif r.output_summary:
                pc = r.output_summary.get("project_id")
                detail = f"Project {pc}" if pc else "Agent run"
            items.append(
                {
                    "id": f"run-{r.id}",
                    "kind": "run",
                    "title": f"Designer Agent run {r.status}",
                    "detail": detail,
                    "status": r.status.value
                    if hasattr(r.status, "value")
                    else str(r.status),
                    "at": r.started_at,
                }
            )

        items.sort(key=lambda x: x["at"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return items[:limit]

    def latest_project(self, merchant_id: uuid.UUID) -> DesignProject | None:
        """The newest project, or None. One query — not two via list_projects."""
        return self.db.scalar(
            select(DesignProject)
            .where(DesignProject.merchant_id == merchant_id)
            .order_by(DesignProject.created_at.desc(), DesignProject.id.desc())
            .limit(1)
        )

    def latest_brief(self, merchant_id: uuid.UUID) -> CreativeBrief | None:
        """The newest CURRENT brief across all projects, or None.

        ``is_current == 1`` is required so a superseded revision can never be
        reported as the latest brief.
        """
        return self.db.scalar(
            select(CreativeBrief)
            .where(
                CreativeBrief.merchant_id == merchant_id,
                CreativeBrief.is_current == 1,
            )
            .order_by(CreativeBrief.created_at.desc(), CreativeBrief.id.desc())
            .limit(1)
        )


# Common aliases for direct image generation without requiring a pre-existing
# design asset or a successful Designer Agent brief.
DesignerService.request_direct_image_generation = DesignerService.request_image_generation
DesignerService.direct_image_generation = DesignerService.request_image_generation
DesignerService.generate_image = DesignerService.request_image_generation
DesignerService.generate_direct_image = DesignerService.request_image_generation
DesignerService.direct_generate_image = DesignerService.request_image_generation

__all__ = [
    "DesignerNotFound",
    "DesignerService",
    "DesignerValidationError",
    "validate_brief",
]
