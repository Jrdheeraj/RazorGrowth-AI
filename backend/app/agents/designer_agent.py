"""
Designer Agent — AI Growth Team Creative Specialist.

The Designer Agent focuses on campaign creative concepts, messaging variations,
experiment concepts, UX recommendations, creative direction, and creative
specifications for growth initiatives.

WHAT CHANGED, AND WHY
---------------------
Previously this agent produced three hard-coded findings about Razorpay retry
UX regardless of the objective it was given, persisted them only when it ran
inside an Agent Debate (so ``mode="team"`` produced nothing at all), never
called the LLM, and ignored ``ctx.shared``. Its five declared tools were
labels with no implementations behind them.

It now:

  * gathers real, authorized observations — RAG context, Growth Radar signals
    and opportunities, plus the Marketing and Product findings already in
    ``ctx.shared`` — and passes THOSE to the model;
  * asks the model for a structured ``CreativeBriefSpec`` (see
    ``schemas/designer.py``) and refuses to store anything the schema or the
    validator rejects;
  * persists a real ``DesignProject`` + versioned ``CreativeBrief`` +
    ``DesignAsset`` rows in EVERY mode, linked to the real
    ``orchestrator_run_id`` and, in a debate, to the real ``debate_id``;
  * still writes Agent Debate findings/messages in a debate, because the
    Manager's synthesis reads those — so debate behaviour is preserved, not
    replaced;
  * publishes structured output on ``ctx.shared["designer_findings"]`` for the
    Software Agent and the Manager, which already read that key.

It still never approves its own work, never executes an external write, and
never invents a brand guideline, a metric or a measured outcome. A brief built
only from hypotheses is rejected rather than stored.

IMAGE GENERATION (PATH A)
-------------------------
Once a brief has been generated AND persisted, this agent hands it to the
one configured image provider — Cloudflare Workers AI
(``@cf/black-forest-labs/flux-1-schnell``) — and stores the resulting image
through the normal asset/version system. This is the LLM-ASSISTED path and it
is deliberately ordered after the brief: a run that never produced a brief
never reaches the image provider.

An image failure is reported as an image failure. It never demotes the brief
that was already stored and never rewrites the run status, because the
research is real and complete regardless of whether the renderer answered.

The other path — rendering a plain user description with no brief and no LLM
call at all — lives in ``DesignerService.request_image_generation`` and is
reachable directly from ``POST /api/designer/image-generation``. It is not a
Designer Agent run and is never reported as one.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.agents.base import AgentContext, AgentResult, BaseGrowthAgent
from backend.app.agents.permissions import (
    AGENT_PERMISSIONS,
    READ_CAMPAIGNS,
    READ_CUSTOMERS,
    READ_MERCHANT,
    READ_OPPORTUNITIES,
)
from backend.app.models.agent_debate import AgentFinding, AgentMessage
from backend.app.models.enums import (
    AgentSpecialty,
    DesignAssetKind,
    DesignReviewStatus,
    FindingType,
)
from backend.app.repositories.agent_debate import (
    AgentFindingRepository,
    AgentMessageRepository,
)
from backend.app.schemas.designer import (
    CreativeBriefSpec,
    UXAuditResult,
    UXFinding,
)
from backend.app.services.customer_intelligence import CustomerIntelligenceService
from backend.app.services.designer_service import (
    DesignerService,
    DesignerValidationError,
    validate_brief,
)

log = logging.getLogger(__name__)


class DesignerAgent(BaseGrowthAgent):
    """
    Designer Agent — AI Growth Team Creative Specialist.

    Responsibilities:
    - Campaign creative concepts and visual direction
    - Messaging variations and copy strategy
    - Experiment creative concepts (A/B test variants)
    - UX recommendations for growth funnels
    - Creative direction and brand alignment
    - Creative specifications for implementation

    The Designer Agent does NOT execute creatives — it produces structured
    creative briefs and specifications for human review and approval. When an
    image provider is configured it will render a real image from a brief it
    has already persisted, but that image is still work for a human to accept
    and is never auto-approved.
    """

    NAME = "DesignerAgent"
    DESCRIPTION = (
        "Creative specialist for the AI Growth Team. Designs campaign "
        "creatives, messaging strategies, experiment variants, and UX "
        "recommendations. Produces structured creative briefs for human "
        "review, and renders real images from those briefs when an image "
        "provider is configured — never executes production creatives."
    )
    PERMISSIONS = frozenset({
        READ_MERCHANT,
        READ_CAMPAIGNS,
        READ_CUSTOMERS,
        # Growth Radar signals and opportunities are the agent's evidence for
        # "why this design, now". Granted so radar context can be read.
        READ_OPPORTUNITIES,
    })
    TOOLS = ("creative_concept", "messaging_strategy", "experiment_variants", "ux_recommendations", "creative_brief")

    def _run(self, ctx: AgentContext, result: AgentResult) -> None:
        db: Session = ctx.db
        merchant_id: uuid.UUID = ctx.merchant_id
        task_id = ctx.params.get("task_id")
        objective = ctx.params.get("objective", "Create compelling growth creatives")
        phase = ctx.params.get("phase", "investigate")

        # Get debate context (optional for AI Team workspace mode)
        debate_id = ctx.params.get("debate_id")
        finding_repo = None
        message_repo = None
        if debate_id:
            debate_id = uuid.UUID(str(debate_id))
            finding_repo = AgentFindingRepository(db)
            message_repo = AgentMessageRepository(db)

        if phase in ("investigate", "work"):
            self._run_investigation(ctx, result, finding_repo, message_repo, debate_id, task_id, merchant_id, objective)
        elif phase == "cross_examine" and message_repo and debate_id:
            self._run_cross_examination(ctx, result, finding_repo, message_repo, debate_id, merchant_id)
        elif phase == "rebut" and message_repo and debate_id:
            self._run_rebuttal(ctx, result, finding_repo, message_repo, debate_id, merchant_id)

    # ── real evidence gathering ───────────────────────────────────────────

    def _gather_observations(
        self, ctx: AgentContext, merchant_id: uuid.UUID, objective: str
    ) -> dict[str, Any]:
        """Collect AUTHORIZED context for this merchant. Never invented.

        Sources, in order of authority:

          1. Growth Radar signals + opportunities already persisted for this
             merchant (a real detection run's output).
          2. The Agentic RAG context the orchestrator built for this run
             (``ctx.shared["rag_context"]``) — verified facts, derived metrics
             and retrieved knowledge.
          3. The Marketing and Product findings already on ``ctx.shared``.
          4. Customer segment distribution from the customer-intelligence
             service.

        If there is nothing grounded here, the run records
        ``INSUFFICIENT_EVIDENCE`` instead of asking the model to invent a brief.
        """
        db = ctx.db
        observations: dict[str, Any] = {
            "objective": objective,
            "radar_signals": [],
            "radar_opportunities": [],
            "rag": {},
            "marketing_findings": {},
            "product_findings": {},
            "segments": {},
        }

        # ── 1. Growth Radar (real rows only) ──
        try:
            from backend.app.models.growth_signal import GrowthSignal
            from backend.app.models.enums import SignalStatus
            from backend.app.models.opportunity import GrowthOpportunity

            signals = list(
                db.scalars(
                    select(GrowthSignal)
                    .where(
                        GrowthSignal.merchant_id == merchant_id,
                        GrowthSignal.status == SignalStatus.active,
                    )
                    .order_by(GrowthSignal.detected_at.desc())
                    .limit(10)
                ).all()
            )
            observations["radar_signals"] = [
                {
                    "id": str(s.id),
                    "signal_type": s.signal_type
                    if isinstance(s.signal_type, str)
                    else str(getattr(s.signal_type, "value", s.signal_type)),
                    "title": s.title,
                    "metric": s.metric,
                    "current_value": float(s.current_value or 0),
                    "change_percentage": float(s.change_percentage)
                    if s.change_percentage is not None
                    else None,
                    "detected_at": s.detected_at.isoformat()
                    if s.detected_at
                    else None,
                }
                for s in signals
            ]

            opps = list(
                db.scalars(
                    select(GrowthOpportunity)
                    .where(GrowthOpportunity.merchant_id == merchant_id)
                    .order_by(GrowthOpportunity.created_at.desc())
                    .limit(10)
                ).all()
            )
            observations["radar_opportunities"] = [
                {
                    "id": str(o.id),
                    "type": o.type if isinstance(o.type, str) else str(getattr(o.type, "value", o.type)),
                    "title": o.title,
                    "description": (o.description or "")[:400],
                    "expected_revenue": float(o.expected_revenue or 0),
                    "confidence": float(o.confidence or 0),
                }
                for o in opps
            ]
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("Designer radar context unavailable: %s", exc)

        # ── 2. Agentic RAG context built for this run ──
        # The orchestrator injects it as ``params["_rag_context"]`` for every
        # step (it is per-step, not shared), so that is read first;
        # ``ctx.shared`` is the fallback for a direct/standalone invocation.
        rag = ctx.params.get("_rag_context") or ctx.shared.get("rag_context") or {}
        if isinstance(rag, dict):
            observations["rag"] = {
                "status": rag.get("status"),
                "data_sufficiency": rag.get("data_sufficiency", {}),
                "verified_facts": rag.get("verified_facts", [])[:12],
                "derived_metrics": rag.get("derived_metrics", {}),
                "retrieved_context": [
                    r.get("content_preview")
                    for r in (rag.get("retrieved_context") or [])[:5]
                    if isinstance(r, dict)
                ],
                "inference_allowed": rag.get("inference_allowed"),
            }

        # ── 3. Sibling agent findings already published this run ──
        observations["marketing_findings"] = ctx.shared.get("marketing_findings", {}) or {}
        observations["product_findings"] = ctx.shared.get("product_findings", {}) or {}

        # ── 4. Customer segment distribution ──
        try:
            insights = CustomerIntelligenceService(db).list_insights(
                merchant_id, limit=500
            )
            segments: dict[str, int] = {}
            for insight in insights:
                seg = getattr(insight.primary_segment, "value", str(insight.primary_segment))
                segments[seg] = segments.get(seg, 0) + 1
            observations["segments"] = segments
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("Designer segment context unavailable: %s", exc)

        observations["grounded_fact_count"] = (
            len(observations["radar_signals"])
            + len(observations["radar_opportunities"])
            + len(observations["rag"].get("verified_facts", []))
        )
        return observations

    def _observation_prompt(self, observations: dict[str, Any]) -> str:
        """The prompt body. Observations only — no instruction to perform.

        The model is told explicitly that anything it did not receive must land
        in ``unknown_context`` rather than being filled in.
        """
        return (
            "Design a creative brief for the objective below.\n\n"
            "REAL OBSERVATIONS FOR THIS WORKSPACE:\n"
            f"{json.dumps(observations, indent=2, default=str)}\n\n"
            "RULES:\n"
            "- Use ONLY the observations above. If something is not there, put it "
            "in `unknown_context` or an `unknown` evidence statement. Never invent a "
            "brand colour, a metric, a customer preference or a campaign result.\n"
            "- Tag every evidence statement: `observed` (directly supported by an "
            "observation), `derived` (calculated from one), `hypothesis` (proposed, "
            "NOT measured), or `unknown`.\n"
            "- At least one statement must be `observed` or `derived`.\n"
            "- Never state that a design change will increase conversion or revenue. "
            "Propose the measurement instead.\n"
            "- Variants must differ in a way you can describe, and each needs an "
            "evaluation method, not an expected result.\n"
        )

    def _parse_ux_findings(
        self, ctx: AgentContext, result: AgentResult, observations: dict[str, Any]
    ) -> list[UXFinding] | None:
        """Structured UX findings from real observations, or None with a reason.

        Shared by the agent's own run and by ``POST /api/designer/ux-audit`` so
        there is exactly one implementation of a UX audit.
        """
        if ctx.llm is None:
            result.errors.append("llm_not_configured")
            return None
        try:
            out, llm_ms = self._timed(
                ctx.llm.generate_structured,
                "You are the RazorGrowth AI Designer Agent's UX auditor. You report "
                "only what the supplied observations show, separate measured facts "
                "from hypotheses, and never claim a measured conversion or revenue "
                "effect for a change that has not shipped.",
                "Audit the user experience against these REAL observations:\n"
                f"{json.dumps(observations, indent=2, default=str)}\n\n"
                "RULES:\n- Report only issues the observations support.\n"
                "- `expected_impact_direction` is a hypothesis, not a measurement.\n"
                "- Never state a conversion or revenue lift.\n"
                "- If the observations are insufficient, return an empty list.\n",
                UXAuditResult,
                temperature=0.2,
                max_tokens=1800,
            )
            result.llm_ms += llm_ms
            return list(out.findings)
        except Exception as exc:
            result.errors.append(f"ux_audit_failed:{type(exc).__name__}: {exc}")
            return None

    def _parse_brief(
        self, ctx: AgentContext, result: AgentResult, observations: dict[str, Any]
    ) -> CreativeBriefSpec | None:
        """Structured model output -> validated spec, or None with a reason.

        A provider timeout, an empty response or a schema violation is recorded
        as an error on the result. It is NEVER converted into a successful run
        with a partial brief.
        """
        if ctx.llm is None:
            result.errors.append("llm_not_configured")
            return None
        try:
            out, llm_ms = self._timed(
                ctx.llm.generate_structured,
                "You are the RazorGrowth AI Designer Agent. You produce structured "
                "creative briefs grounded strictly in the observations you are "
                "given. You never invent brand, business or customer facts, and you "
                "never assert a measured business outcome for work that has not "
                "shipped.",
                self._observation_prompt(observations),
                CreativeBriefSpec,
                temperature=0.2,
                max_tokens=2400,
            )
            result.llm_ms += llm_ms
            return out
        except Exception as exc:
            # Distinguish "the LLM provider refused" from every other failure,
            # and carry the *category* (quota vs throttling vs auth) so the
            # workspace can tell the merchant whether retrying will help. The
            # raw provider payload stays in the provider layer's log.
            category = getattr(exc, "category", None) or "unknown"
            result.errors.append(f"brief_generation_failed:{category}")
            log.warning(
                "Designer brief generation failed: category=%s attempt_stats=%s",
                category,
                getattr(ctx.llm, "last_call_stats", None),
            )
            return None

    def _run_investigation(
        self,
        ctx: AgentContext,
        result: AgentResult,
        finding_repo: AgentFindingRepository | None,
        message_repo: AgentMessageRepository | None,
        debate_id: uuid.UUID | None,
        task_id: str | None,
        merchant_id: uuid.UUID,
        objective: str,
    ) -> None:
        """Produce and PERSIST a real, evidence-grounded creative brief.

        Persistence happens in every mode. Previously it only occurred inside a
        debate, which meant an AI Team design request produced nothing durable.
        """
        db = ctx.db
        designer = DesignerService(db)

        observations = self._gather_observations(ctx, merchant_id, objective)
        result.output["observations"] = {
            "grounded_fact_count": observations["grounded_fact_count"],
            "radar_signals": len(observations["radar_signals"]),
            "radar_opportunities": len(observations["radar_opportunities"]),
            "segments": len(observations["segments"]),
            "rag_status": observations["rag"].get("status"),
        }

        if observations["grounded_fact_count"] == 0:
            # Honest refusal: no observations means no brief. The run still
            # completes (it did its job) but records why nothing was produced.
            result.output["decision"] = "INSUFFICIENT_EVIDENCE"
            result.output["brief_persisted"] = False
            result.output["summary"] = (
                "No Growth Radar signals, opportunities or verified facts were "
                "available for this workspace, so no creative brief was generated."
            )
            if message_repo and debate_id:
                message_repo.create(
                    debate_id=debate_id,
                    merchant_id=merchant_id,
                    from_agent=AgentSpecialty.designer.value,
                    to_agent=None,
                    message_type="opening",
                    content=(
                        "Creative & UX Advisor: no measured signals or business "
                        "facts were available to ground a creative direction, so "
                        "I am not proposing one. Guessing would be worse than "
                        "saying nothing."
                    ),
                    references=[{"round": 1, "grounded_fact_count": 0}],
                )
            return

        spec = self._parse_brief(ctx, result, observations)
        if spec is None:
            # A run that produced no brief is not a successful run. Mark it
            # failed so the workspace never reports work that was not done;
            # BaseGrowthAgent.run() preserves this rather than overwriting it.
            result.status = "failed"
            result.output["brief_persisted"] = False
            # Name the service and whether retrying helps, instead of echoing a
            # bare exception class at the merchant.
            last = result.errors[-1] if result.errors else ""
            if last.startswith("brief_generation_failed:"):
                from backend.app.ai.llm.provider import describe_llm_failure

                category = last.split(":", 1)[1]
                result.output["llm_failure_category"] = category
                result.output["summary"] = (
                    "Could not generate a creative brief. " + describe_llm_failure(category)
                )
            else:
                result.output["summary"] = "Could not generate a creative brief: " + last
            return

        # Correlate with the REAL cycle / run. The orchestrator mints
        # orchestrator_run_id; reusing it means design work is never a
        # parallel cycle.
        cycle_id = ctx.params.get("orchestrator_run_id")
        project_id = self._current_run_id(ctx)

        # Validate BEFORE creating any project row. A refused brief must leave
        # no trace: an empty project with no brief and no outputs would show up
        # on the dashboard as work that was produced when it was not.
        try:
            validate_brief(spec)
        except DesignerValidationError as exc:
            result.errors.append(f"brief_refused:{exc.reason}")
            result.output["brief_persisted"] = False
            # ``exc.detail`` may itself carry a human-readable "reason", so the
            # machine reason is kept under its own key instead of being
            # overwritten by a merged dict.
            result.output["validation_refusal"] = {
                "reason": exc.reason,
                "detail": exc.detail,
            }
            result.output["summary"] = (
                f"The generated brief was refused before storage ({exc.reason})."
            )
            return

        radar_refs = [
            {
                "kind": "growth_signal",
                "id": s["id"],
                "signal_type": s["signal_type"],
                "title": s["title"],
            }
            for s in observations["radar_signals"][:5]
        ] + [
            {
                "kind": "growth_opportunity",
                "id": o["id"],
                "type": o["type"],
                "title": o["title"],
            }
            for o in observations["radar_opportunities"][:5]
        ]

        project = designer.create_project(
            merchant_id,
            objective=objective,
            title=spec.title,
            project_type=spec.project_type,
            analysis_cycle_id=cycle_id,
            debate_id=debate_id,
        )

        try:
            brief = designer.store_brief(
                merchant_id,
                project,
                spec,
                review_status=DesignReviewStatus.pending_review,
                analysis_cycle_id=cycle_id,
                agent_run_id=project_id,
                llm_provider=getattr(ctx.llm, "provider", None),
                llm_model=getattr(ctx.llm, "model", None),
                radar_references=radar_refs or None,
            )
        except DesignerValidationError as exc:  # pragma: no cover - defensive
            result.errors.append(f"brief_refused:{exc.reason}")
            result.output["brief_persisted"] = False
            result.output["validation_refusal"] = {
                "reason": exc.reason,
                "detail": exc.detail,
            }
            result.output["summary"] = (
                f"The generated brief was refused before storage ({exc.reason})."
            )
            return

        result.output["project_id"] = str(project.id)
        result.output["brief_id"] = str(brief.id)
        result.output["brief_version"] = brief.version
        result.output["brief_persisted"] = True
        result.output["variant_count"] = len(spec.variants)
        result.output["ux_finding_count"] = len(spec.ux_findings)
        result.output["radar_references"] = radar_refs
        result.output["recommendations"] = [
            v.title for v in spec.variants
        ] or [spec.objective]
        result.output["summary"] = spec.objective
        result.output["brand_constraints"] = list(spec.brand_constraints)
        result.output["handoff_notes"] = {
            "variants": [v.model_dump() for v in spec.variants],
            "ux_findings": [f.model_dump() for f in spec.ux_findings],
            "evidence": [e.model_dump() for e in spec.evidence],
            "open_questions": list(spec.open_questions),
        }
        # Structured output for sibling agents that already read this key.
        result.output["designer_handoff"] = {
            "brief_id": str(brief.id),
            "project_id": str(project.id),
            "title": spec.title,
            "project_type": spec.project_type,
            "layout_direction": spec.layout_direction,
            "accessibility_considerations": list(spec.accessibility_considerations),
            "variants": [v.model_dump() for v in spec.variants],
            "confidence": spec.confidence,
        }
        result.insights_generated += 1

        # PATH A — the brief exists, so it can now be rendered for real.
        # Deliberately last: a brief that was refused or never produced must
        # never reach an image provider.
        self._render_brief_creative(ctx, result, designer, merchant_id, project, brief, spec)

        if debate_id:
            self._record_debate_outputs(
                result,
                finding_repo,
                message_repo,
                debate_id=debate_id,
                task_id=task_id,
                merchant_id=merchant_id,
                spec=spec,
                brief=brief,
                observations=observations,
            )

    # ── Path A: brief -> real image ────────────────────────────────────────
    #
    # PATH A IS LLM-ASSISTED. It is only ever reached from a brief that was
    # generated by the configured LLM, validated, and persisted. It is a
    # different operation from Path B (``POST /designer/image-generation``),
    # which renders a plain user description with no LLM call at all; the two
    # are never conflated, and this method never reports a brief it did not
    # receive.

    #: FLUX.1 [schnell] refuses prompts over 2048 characters. The brief is
    #: clamped here so an over-long objective costs no round trip.
    _IMAGE_PROMPT_MAX = 1800

    def _render_brief_creative(
        self,
        ctx: AgentContext,
        result: AgentResult,
        designer: DesignerService,
        merchant_id: uuid.UUID,
        project: Any,
        brief: Any,
        spec: CreativeBriefSpec,
    ) -> None:
        """Render a real image from the brief that was just stored.

        HONESTY CONTRACT
        ----------------
        * The brief is already persisted. An image failure is recorded on the
          run and NEVER demotes the brief or rewrites the run's status — the
          merchant keeps the research they actually paid for.
        * The converse is absolute: no brief, no image. This is called after
          ``store_brief`` succeeded, never before.
        * ``result.output["image_generation"]`` always carries the provider's
          real state. ``completed`` appears only when validated bytes were
          stored; a provider refusal is reported as ``failed``/``unavailable``
          with its reason.
        """
        availability = designer.image_generation_status()
        if availability.get("status") != "available":
            # No provider configured, or the feature is switched off. Recorded,
            # not raised: the brief above is still real and still reviewable.
            result.output["image_generation"] = dict(availability)
            return

        prompt = self._image_prompt_from_brief(spec)
        try:
            asset = designer.add_asset(
                merchant_id,
                project,
                # Deliberately NOT ``rendered_image``: no bytes exist yet, and
                # filing an unrendered creative as a rendered one is the exact
                # conflation this codebase refuses. A successful render below
                # promotes the kind once the image is real.
                kind=DesignAssetKind.specification,
                title=spec.title,
                content={
                    "kind": DesignAssetKind.specification.value,
                    "title": spec.title,
                    "rendered": False,
                    "project_type": spec.project_type,
                    "layout_direction": spec.layout_direction,
                },
                brief_id=brief.id,
                change_summary="Creative direction from the generated brief",
                rationale=(
                    "Direction only. No image bytes exist for this version yet."
                ),
                evidence=[e.model_dump() for e in spec.evidence] or None,
            )
            state = designer.request_image_generation(
                merchant_id, asset.id, prompt=prompt
            )
        except Exception as exc:  # pragma: no cover - defensive
            # The brief is already stored and must survive. An unexpected
            # failure is reported as a failure, never as a silent success.
            log.warning(
                "designer image render raised unexpectedly (merchant=%s): %s",
                merchant_id,
                type(exc).__name__,
            )
            state = {
                "status": "failed",
                "reason": "The image could not be generated for this brief.",
                "code": "IMAGE_RENDER_ERROR",
                "asset_reference": None,
            }
        result.output["image_generation"] = dict(state)

    def _image_prompt_from_brief(self, spec: CreativeBriefSpec) -> str:
        """Compose the provider prompt from the validated brief.

        Only brief fields are used. Nothing is invented, and the result is
        clamped to the provider's own limit.
        """
        parts: list[str] = [spec.objective]
        if spec.layout_direction:
            parts.append(f"Layout and composition: {spec.layout_direction}")
        if spec.brand_constraints:
            parts.append(
                "Brand constraints: " + ", ".join(spec.brand_constraints)
            )
        variant = spec.variants[0].title if spec.variants else ""
        if variant:
            parts.append(f"Creative direction: {variant}")
        joined = " ".join(p for p in parts if p).strip()
        return joined[: self._IMAGE_PROMPT_MAX].strip()

    def _current_run_id(self, ctx: AgentContext) -> uuid.UUID | None:
        """The AgentRun row for THIS step, if one is identifiable.

        The orchestrator writes an ``agent_runs`` row before calling the agent;
        this matches it by ``orchestrator_run_id`` + agent name so a brief can
        point back at the real run. Returns None when the agent is invoked
        outside the orchestrator, which is not an error.
        """
        cycle_id = ctx.params.get("orchestrator_run_id")
        if not cycle_id:
            return None
        try:
            from backend.app.models.agent_run import AgentRun

            row = ctx.db.scalar(
                select(AgentRun)
                .where(
                    AgentRun.agent_name == self.NAME,
                    AgentRun.orchestrator_run_id == str(cycle_id),
                )
                .order_by(AgentRun.started_at.desc())
                .limit(1)
            )
            return row.id if row is not None else None
        except Exception:  # pragma: no cover - defensive
            return None

    def _record_debate_outputs(
        self,
        result: AgentResult,
        finding_repo: AgentFindingRepository | None,
        message_repo: AgentMessageRepository | None,
        *,
        debate_id: uuid.UUID,
        task_id: str | None,
        merchant_id: uuid.UUID,
        spec: CreativeBriefSpec,
        brief: Any,
        observations: dict[str, Any],
    ) -> None:
        """Mirror the brief into the debate so synthesis can read it.

        The debate ledger is what the Manager aggregates, so the brief is
        represented there as real findings carrying the same evidence. This
        does not replace the brief — it references it.
        """
        evidence_payload = [e.model_dump() for e in spec.evidence][:6]

        if finding_repo is not None:
            self._create_finding(
                finding_repo, debate_id, task_id, merchant_id,
                finding_type=FindingType.supporting,
                title=spec.title,
                description=(
                    f"{spec.objective}\n\n"
                    f"Project {brief.id} (v{brief.version}). "
                    f"{len(spec.variants)} variants proposed."
                ),
                evidence=evidence_payload,
                confidence=spec.confidence or 0.5,
                uncertainty_notes="; ".join(spec.unknown_context) or None,
                supports_recommendation=True,
            )
            result.output["findings_created"] = result.output.get("findings_created", 0) + 1

            # UX findings become their own debate findings so the Product
            # Agent's synthesis sees them distinctly from the creative brief.
            for finding in spec.ux_findings:
                self._create_finding(
                    finding_repo, debate_id, task_id, merchant_id,
                    finding_type=FindingType.neutral,
                    title=f"UX: {finding.title}",
                    description=(
                        f"{finding.observed_issue}\n\n"
                        f"Proposed: {finding.proposed_improvement}\n"
                        f"Impact hypothesis ({finding.expected_impact_direction}, "
                        f"{finding.expected_impact_magnitude} magnitude, NOT measured): "
                        f"{finding.user_impact_hypothesis}"
                    ),
                    evidence=evidence_payload,
                    confidence=finding.confidence or 0.5,
                    uncertainty_notes=(
                        "A design change that has not shipped has no measured "
                        "effect; this direction is a hypothesis."
                    ),
                    supports_recommendation=None,
                )
                result.output["findings_created"] = result.output.get("findings_created", 0) + 1

        if message_repo is not None:
            grounded = observations["grounded_fact_count"]
            message_repo.create(
                debate_id=debate_id,
                merchant_id=merchant_id,
                from_agent=AgentSpecialty.designer.value,
                to_agent=None,
                message_type="opening",
                content=(
                    f"Creative & UX Advisor: grounded in {grounded} real observation(s) "
                    f"for this workspace. Brief: {spec.title}. "
                    f"Direction: {spec.layout_direction or 'not specified'}. "
                    f"{len(spec.variants)} variants and {len(spec.ux_findings)} UX "
                    f"findings are stored on project {brief.id} for human review. "
                    f"Stored as a brief — not a rendered creative, and nothing is "
                    f"executed until approved."
                ),
                references=[
                    {
                        "round": 1,
                        "brief_id": str(brief.id),
                        "project_id": str(brief.project_id),
                        "grounded_fact_count": grounded,
                    }
                ],
            )

    def _run_cross_examination(
        self,
        ctx: AgentContext,
        result: AgentResult,
        finding_repo: AgentFindingRepository,
        message_repo: AgentMessageRepository,
        debate_id: uuid.UUID,
        merchant_id: uuid.UUID,
    ) -> None:
        """Challenge the Software Agent from the brief actually produced.

        The question is now grounded in the persisted brief's own open
        questions rather than a fixed Razorpay script, so the cross-examination
        is about THIS run's design work.
        """
        brief_id = result.output.get("brief_id")
        open_questions: list[str] = []
        if brief_id:
            try:
                row = DesignerService(ctx.db).get_brief(merchant_id, uuid.UUID(str(brief_id)))
                open_questions = list(row.open_questions or [])
            except Exception:  # pragma: no cover - defensive
                open_questions = []
        if not open_questions:
            open_questions = [
                "which components can be implemented without new third-party dependencies"
            ]

        message_repo.create(
            debate_id=debate_id,
            merchant_id=merchant_id,
            from_agent=AgentSpecialty.designer.value,
            to_agent=AgentSpecialty.software.value,
            message_type="challenge",
            content=(
                "Creative & UX Advisor -> Technical Feasibility: the brief I stored "
                f"({brief_id or 'no brief'}) has these open questions that decide "
                f"whether it is buildable: " + "; ".join(open_questions[:3])
            ),
            references=[
                {
                    "round": 2,
                    "target": "software",
                    "brief_id": brief_id,
                    "open_questions": open_questions[:3],
                }
            ],
        )

    def _run_rebuttal(
        self,
        ctx: AgentContext,
        result: AgentResult,
        finding_repo: AgentFindingRepository,
        message_repo: AgentMessageRepository,
        debate_id: uuid.UUID,
        merchant_id: uuid.UUID,
    ) -> None:
        """Respond to the Product Agent using the stored UX findings."""
        ux: list[dict[str, Any]] = []
        brief_id = result.output.get("brief_id")
        if brief_id:
            try:
                row = DesignerService(ctx.db).get_brief(merchant_id, uuid.UUID(str(brief_id)))
                validation = row.validation or {}
                ux = list(validation.get("ux_findings") or [])
            except Exception:  # pragma: no cover - defensive
                ux = []

        if ux:
            detail = "; ".join(
                f"{f.get('title')}: {f.get('proposed_improvement', '')[:140]}"
                for f in ux[:2]
            )
        else:
            detail = (
                "the brief recorded no UX findings, so I am making no UX claim "
                "in this round"
            )

        message_repo.create(
            debate_id=debate_id,
            merchant_id=merchant_id,
            from_agent=AgentSpecialty.designer.value,
            to_agent=AgentSpecialty.product.value,
            message_type="rebuttal",
            content=(
                "Creative & UX Advisor -> Product Strategist: grounding my position "
                f"in the UX findings on the stored brief ({brief_id or 'none'}): "
                f"{detail}. These are hypotheses pending measurement, not measured "
                f"effects, and I am not claiming a conversion or revenue outcome."
            ),
            references=[
                {
                    "round": 3,
                    "target": "product",
                    "brief_id": brief_id,
                    "ux_finding_count": len(ux),
                }
            ],
        )

    def _create_finding(
        self,
        finding_repo: AgentFindingRepository,
        debate_id: uuid.UUID,
        task_id: str | None,
        merchant_id: uuid.UUID,
        finding_type: FindingType,
        title: str,
        description: str,
        evidence: list[dict[str, Any]],
        confidence: float,
        uncertainty_notes: str | None = None,
        supports_recommendation: bool | None = None,
    ) -> AgentFinding:
        task_uuid = uuid.UUID(str(task_id)) if task_id else None
        finding = finding_repo.create(
            debate_id=debate_id,
            merchant_id=merchant_id,
            task_id=task_uuid,
            agent_specialty=AgentSpecialty.designer,
            finding_type=finding_type,
            title=title,
            description=description,
            evidence=evidence,
            confidence=confidence,
            uncertainty_notes=uncertainty_notes,
            supports_recommendation=supports_recommendation,
        )
        return finding
