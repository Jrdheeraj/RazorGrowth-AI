"""Designer Agent — creative intelligence, validation and evidence provenance.

Covers the guarantees that matter most and are easiest to regress:

  * a brief is grounded in REAL observations, never invented;
  * a brief with no observed/derived evidence is REFUSED, not stored;
  * a provider timeout / malformed output records a failure, never a success;
  * an unsupported measured-outcome claim is refused;
  * absent LLM configuration yields an honest no-op, not a fabricated brief;
  * persistence happens in ``team`` mode, not only inside a debate;
  * the stored brief is linked to the real AI Team cycle.

The LLM is an in-process fake (same approach as tests/test_ai_phase3.py), so
no test touches the network.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from backend.app.agents.base import AgentContext
from backend.app.agents.permissions import (
    AGENT_PERMISSIONS,
    FORBIDDEN_CAPABILITIES,
)
from backend.app.agents.registry import AGENT_INSTANCES
from backend.app.models.enums import (
    Currency,
    MerchantStatus,
    SignalStatus,
)
from backend.app.models.growth_signal import GrowthSignal
from backend.app.models.merchant import Merchant
from backend.app.schemas.designer import (
    CreativeBriefSpec,
    DesignerStatusResponse,
    Evidence,
    UXAuditResult,
)
from backend.app.services.designer_service import (
    DesignerService,
    DesignerValidationError,
    validate_brief,
)


# ── helpers ──────────────────────────────────────────────────────────────


def make_merchant(db_session: Session, tag: str = "designer") -> Merchant:
    m = Merchant(
        name=f"{tag} {uuid.uuid4().hex[:6]}",
        slug=f"{tag}-{uuid.uuid4().hex[:10]}",
        email=f"{tag}@example.com",
        status=MerchantStatus.active,
        currency=Currency.INR,
    )
    db_session.add(m)
    db_session.commit()
    return m


def make_signal(db_session: Session, merchant: Merchant) -> GrowthSignal:
    s = GrowthSignal(
        merchant_id=merchant.id,
        signal_key=f"sig-{uuid.uuid4().hex[:12]}",
        signal_type="payment_failures",
        status=SignalStatus.active,
        title="Payment failures rising",
        metric="failed_payment_events",
        current_value=12,
        comparison_value=8,
        change_percentage=50.0,
        window_days=30,
        confidence=0.8,
        detected_at=datetime.now(timezone.utc),
    )
    db_session.add(s)
    db_session.commit()
    return s


class FakeLLM:
    """Structured-output provider stub."""

    provider = "fake"
    model = "fake-model-1"

    def __init__(self, mode: str = "ok") -> None:
        self.mode = mode
        self.calls = 0

    def generate_structured(self, system, user, schema, *, temperature=0.0, max_tokens=2048):
        self.calls += 1
        if self.mode == "timeout":
            raise TimeoutError("provider timed out")
        if self.mode == "malformed":
            return schema.model_validate({"totally": "wrong"})
        if self.mode == "claim":
            return schema.model_validate(
                {
                    "title": "Outcome claim",
                    "objective": "Lift everything",
                    "project_type": "messaging",
                    "content_requirements": ["This will increase conversion by 20%"],
                    "evidence": [{"statement": "s", "basis": "observed"}],
                }
            )
        if schema is UXAuditResult:
            return schema.model_validate(
                {
                    "findings": [
                        {
                            "title": "Checkout retry clarity",
                            "observed_issue": "Failed payments observed",
                            "affected_experience": "Checkout",
                            "user_impact_hypothesis": "Users may abandon",
                            "proposed_improvement": "Inline decline reason",
                            "expected_impact_direction": "helps",
                        }
                    ]
                }
            )
        return schema.model_validate(
            {
                "title": "Summer campaign refresh",
                "objective": "Give the seasonal campaign one coherent visual system",
                "project_type": "campaign_creative",
                "audience": "Repeat buyers",
                "channel": "instagram",
                "layout_direction": "Hero-led single column",
                "variants": [
                    {
                        "variant_key": "control",
                        "title": "Editorial",
                        "objective": "Baseline",
                        "rationale": "Current direction",
                        "evaluation_method": "A/B test",
                        "evidence_refs": [0],
                    },
                    {
                        "variant_key": "variant_a",
                        "title": "Bold type",
                        "objective": "Test bolder hierarchy",
                        "differences": ["Larger display type"],
                        "rationale": "Segment mix hypothesis",
                        "trade_offs": ["Higher production cost"],
                        "evaluation_method": "A/B test",
                        "evidence_refs": [0],
                    },
                ],
                "ux_findings": [
                    {
                        "title": "Retry clarity",
                        "observed_issue": "Failed payments observed",
                        "affected_experience": "Checkout",
                        "user_impact_hypothesis": "Abandonment after decline",
                        "proposed_improvement": "Inline decline reason",
                        "expected_impact_direction": "helps",
                    }
                ],
                "accessibility_considerations": ["4.5:1 body contrast"],
                "open_questions": ["Which fonts are licensed for web?"],
                "evidence": [
                    {
                        "statement": "12 failed payment events in the window",
                        "basis": "observed",
                        "source": "growth_radar",
                        "value": 12,
                    }
                ],
                "confidence": 0.7,
            }
        )


def run_agent(
    db_session: Session,
    merchant: Merchant,
    *,
    llm,
    objective: str = "Refresh the summer campaign creative",
    mode: str = "team",
    cycle_id: str | None = None,
):
    agent = AGENT_INSTANCES["DesignerAgent"]
    params = {"phase": "work" if mode == "team" else "investigate", "objective": objective}
    if cycle_id:
        params["orchestrator_run_id"] = cycle_id
    return agent.execute(
        AgentContext(db=db_session, merchant_id=merchant.id, mode=mode, llm=llm, params=params)
    )


# ── permissions & registry ───────────────────────────────────────────────


class TestDesignerRegistration:
    def test_agent_is_registered_once(self):
        names = [n for n in AGENT_INSTANCES if n == "DesignerAgent"]
        assert names == ["DesignerAgent"]

    def test_holds_no_forbidden_capability(self):
        perms = AGENT_PERMISSIONS["DesignerAgent"]
        assert not (perms & FORBIDDEN_CAPABILITIES)

    def test_registry_and_permission_matrix_agree(self):
        agent = AGENT_INSTANCES["DesignerAgent"]
        assert agent.PERMISSIONS == AGENT_PERMISSIONS["DesignerAgent"]

    def test_declares_its_five_capabilities(self):
        assert set(AGENT_INSTANCES["DesignerAgent"].TOOLS) == {
            "creative_concept",
            "messaging_strategy",
            "experiment_variants",
            "ux_recommendations",
            "creative_brief",
        }


# ── evidence & validation ────────────────────────────────────────────────


class TestEvidenceProvenance:
    def test_observed_evidence_passes(self):
        spec = CreativeBriefSpec(
            title="T",
            objective="O",
            project_type="messaging",
            evidence=[{"statement": "s", "basis": "observed"}],
        )
        report = validate_brief(spec)
        assert report["valid"] is True
        assert report["grounded_evidence_count"] == 1

    def test_hypotheses_alone_are_refused(self):
        # Refused at the SCHEMA layer (Pydantic) before it can reach the
        # service. Either refusal is correct; neither stores a brief.
        with pytest.raises((DesignerValidationError, ValueError)):
            spec = CreativeBriefSpec(
                title="T",
                objective="O",
                project_type="messaging",
                evidence=[{"statement": "s", "basis": "hypothesis"}],
            )
            validate_brief(spec)

    def test_unknown_only_is_refused(self):
        with pytest.raises((DesignerValidationError, ValueError)):
            spec = CreativeBriefSpec(
                title="T",
                objective="O",
                project_type="messaging",
                evidence=[{"statement": "s", "basis": "unknown"}],
            )
            validate_brief(spec)

    def test_no_evidence_at_all_is_refused(self):
        with pytest.raises(DesignerValidationError):
            validate_brief(
                CreativeBriefSpec(title="T", objective="O", project_type="messaging")
            )

    def test_measured_outcome_claim_is_refused(self):
        with pytest.raises(DesignerValidationError) as exc:
            validate_brief(
                CreativeBriefSpec(
                    title="T",
                    objective="O",
                    project_type="messaging",
                    content_requirements=["This will increase conversion by 20%"],
                    evidence=[{"statement": "s", "basis": "observed"}],
                )
            )
        assert exc.value.reason == "UNSUPPORTED_OUTCOME_CLAIM"

    def test_missing_optional_fields_are_reported_not_invented(self):
        spec = CreativeBriefSpec(
            title="T",
            objective="O",
            project_type="brand_identity",
            evidence=[{"statement": "s", "basis": "observed"}],
            unknown_context=["no brand guidelines on file"],
        )
        report = validate_brief(spec)
        assert "audience" in report["missing_required"]
        assert "no_variants_proposed" in report["warnings"]

    def test_evidence_basis_is_constrained(self):
        with pytest.raises(Exception):
            Evidence(statement="s", basis="vibes")  # type: ignore[arg-type]

    def test_duplicate_variant_keys_rejected(self):
        with pytest.raises(Exception):
            CreativeBriefSpec(
                title="T",
                objective="O",
                project_type="messaging",
                variants=[
                    {"variant_key": "a", "title": "t", "objective": "o", "rationale": "r", "evaluation_method": "m"},
                    {"variant_key": "a", "title": "t2", "objective": "o2", "rationale": "r2", "evaluation_method": "m2"},
                ],
            )

    def test_non_hex_colour_rejected(self):
        with pytest.raises(Exception):
            CreativeBriefSpec(
                title="T",
                objective="O",
                project_type="brand_identity",
                color_guidance={"palette": ["coral"]},
            )


# ── agent behaviour ──────────────────────────────────────────────────────


class TestDesignerAgentRun:
    def test_no_observations_produces_no_brief(self, db_session: Session):
        merchant = make_merchant(db_session, "noev")
        result = run_agent(db_session, merchant, llm=FakeLLM())
        assert result.status == "completed"
        assert result.output["decision"] == "INSUFFICIENT_EVIDENCE"
        assert result.output["brief_persisted"] is False
        assert DesignerService(db_session).count_projects(merchant.id) == 0

    def test_brief_is_persisted_in_team_mode(self, db_session: Session):
        merchant = make_merchant(db_session, "team")
        make_signal(db_session, merchant)
        result = run_agent(db_session, merchant, llm=FakeLLM())
        assert result.status == "completed"
        assert result.output["brief_persisted"] is True
        assert result.output["variant_count"] == 2
        assert result.output["ux_finding_count"] == 1
        svc = DesignerService(db_session)
        assert svc.count_projects(merchant.id) == 1

    def test_persisted_brief_carries_radar_provenance(self, db_session: Session):
        merchant = make_merchant(db_session, "prov")
        make_signal(db_session, merchant)
        result = run_agent(db_session, merchant, llm=FakeLLM())
        svc = DesignerService(db_session)
        project = svc.get_project(merchant.id, uuid.UUID(result.output["project_id"]))
        brief = svc.get_current_brief(merchant.id, project.id)
        assert brief.radar_references, "brief must reference the real signal"
        assert brief.evidence[0]["basis"] == "observed"
        assert brief.review_status.value == "pending_review"

    def test_brief_links_to_the_real_cycle(self, db_session: Session):
        merchant = make_merchant(db_session, "cycle")
        make_signal(db_session, merchant)
        result = run_agent(db_session, merchant, llm=FakeLLM(), cycle_id="cycle-abc-123")
        svc = DesignerService(db_session)
        project = svc.get_project(merchant.id, uuid.UUID(result.output["project_id"]))
        assert project.analysis_cycle_id == "cycle-abc-123"

    def test_provider_timeout_is_a_recorded_failure(self, db_session: Session):
        merchant = make_merchant(db_session, "timeout")
        make_signal(db_session, merchant)
        result = run_agent(db_session, merchant, llm=FakeLLM("timeout"))
        assert any("brief_generation_failed" in e for e in result.errors)
        assert result.output["brief_persisted"] is False
        assert DesignerService(db_session).count_projects(merchant.id) == 0

    def test_malformed_model_output_stores_nothing(self, db_session: Session):
        merchant = make_merchant(db_session, "malformed")
        make_signal(db_session, merchant)
        result = run_agent(db_session, merchant, llm=FakeLLM("malformed"))
        assert any("brief_generation_failed" in e for e in result.errors)
        assert result.output["brief_persisted"] is False
        assert DesignerService(db_session).count_projects(merchant.id) == 0

    def test_unsupported_claim_is_refused_before_storage(self, db_session: Session):
        merchant = make_merchant(db_session, "claim")
        make_signal(db_session, merchant)
        result = run_agent(db_session, merchant, llm=FakeLLM("claim"))
        assert result.output["brief_persisted"] is False
        assert (
            result.output["validation_refusal"]["reason"] == "UNSUPPORTED_OUTCOME_CLAIM"
        )
        assert DesignerService(db_session).count_projects(merchant.id) == 0

    def test_missing_llm_is_an_honest_no_op(self, db_session: Session):
        merchant = make_merchant(db_session, "nollm")
        make_signal(db_session, merchant)
        result = run_agent(db_session, merchant, llm=None)
        assert result.output["brief_persisted"] is False
        assert "llm_not_configured" in result.errors
        assert DesignerService(db_session).count_projects(merchant.id) == 0

    def test_agent_publishes_structured_handoff(self, db_session: Session):
        merchant = make_merchant(db_session, "handoff")
        make_signal(db_session, merchant)
        result = run_agent(db_session, merchant, llm=FakeLLM())
        handoff = result.output["designer_handoff"]
        assert handoff["brief_id"] == result.output["brief_id"]
        assert len(handoff["variants"]) == 2
        assert handoff["project_type"] == "campaign_creative"

    def test_ux_audit_returns_typed_findings(self, db_session: Session):
        merchant = make_merchant(db_session, "ux")
        make_signal(db_session, merchant)
        agent = AGENT_INSTANCES["DesignerAgent"]
        from backend.app.agents.base import AgentResult

        probe = AgentResult(agent_name="DesignerAgent")
        findings = agent._parse_ux_findings(
            AgentContext(db=db_session, merchant_id=merchant.id, llm=FakeLLM()),
            probe,
            {"grounded_fact_count": 1},
        )
        assert findings and findings[0].affected_experience == "Checkout"

    def test_ux_audit_without_llm_reports_the_reason(self, db_session: Session):
        merchant = make_merchant(db_session, "uxno")
        agent = AGENT_INSTANCES["DesignerAgent"]
        from backend.app.agents.base import AgentResult

        probe = AgentResult(agent_name="DesignerAgent")
        assert (
            agent._parse_ux_findings(
                AgentContext(db=db_session, merchant_id=merchant.id, llm=None),
                probe,
                {"grounded_fact_count": 1},
            )
            is None
        )
        assert "llm_not_configured" in probe.errors
