"""
PaymentRecoveryAgent — reason-aware, measurable failed-payment recovery.

Upgraded from the original implementation, which:
  * ignored ``Payment.failure_code`` entirely,
  * multiplied value by a hardcoded 0.25 "assumption",
  * proposed one retry per run with no timing, stop rule or measurement.

This version delegates the reasoning to
:class:`~backend.app.services.payment_recovery.PaymentRecoveryService` and:

  * classifies every failure using verified provider semantics;
  * derives a recovery rate from THIS merchant's own history and withholds a
    projection when history is too thin (never substitutes a constant);
  * plans a bounded retry schedule per failure class;
  * skips customers who must act first instead of burning a retry;
  * proposes at most ``MAX_PROPOSALS`` retries per run, highest value first;
  * hands Marketing an aggregate, privacy-scoped payload for an approved
    reminder campaign.

Safety: proposals enter 'requested' state; approval is human-only; real
Razorpay execution stays disabled unless explicitly enabled; nothing here
marks a payment recovered without verifying an actual captured payment.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.agents.base import AgentContext, AgentResult, BaseGrowthAgent
from backend.app.agents.permissions import (
    AGENT_PERMISSIONS,
    PROPOSE_ACTION,
    assert_permission,
)
from backend.app.models.agent_action import AgentAction
from backend.app.models.enums import OpportunityType, PaymentStatus
from backend.app.models.opportunity import GrowthOpportunity
from backend.app.models.payment import Payment
from backend.app.services.action_service import create_action
from backend.app.services.handoff import handoff_service
from backend.app.services.opportunity_upsert import build_opportunity_key, upsert_opportunity
from backend.app.services.payment_recovery import (
    RETRYABLE,
    PaymentRecoveryService,
    measure_recovery_rate,
)
from backend.app.services.scoring import (
    OpportunityScoringEngine,
    default_risk_for_action_type,
)
from backend.app.services.simulation import SimulationEngine

log = logging.getLogger(__name__)

RECOVERY_WINDOW_DAYS = 30

#: Maximum retry proposals created in a single run. The original proposed
#: exactly one (the largest payment); that is not recovery, it is a sample.
MAX_PROPOSALS = 5

#: Statuses that mean "already handled" for duplicate detection.
_OPEN_RETRY_STATUSES = ("requested", "approved", "executing", "completed")


class PaymentRecoveryAgent(BaseGrowthAgent):
    NAME = "PaymentRecoveryAgent"
    DESCRIPTION = (
        "Classifies real failed payments by provider failure code, measures "
        "this merchant's own recovery rate, plans bounded retry timing, and "
        "proposes approval-gated recovery actions."
    )
    PERMISSIONS = AGENT_PERMISSIONS[NAME]
    TOOLS = ("failed_payment_scan", "recovery_simulation", "phase4_propose")

    def _run(self, ctx: AgentContext, result: AgentResult) -> None:
        db: Session = ctx.db
        merchant_id: uuid.UUID = ctx.merchant_id
        window_days = int(ctx.params.get("window_days", RECOVERY_WINDOW_DAYS))

        # ── 1. Read-only analysis of REAL payment rows ──────────────────────
        analysis = PaymentRecoveryService(db).analyse(
            merchant_id, window_days=window_days
        )
        result.output["analysis"] = analysis
        result.output["failed_payments"] = {
            "count": analysis["failed_payment_count"],
            "total_value": analysis["failed_value_inr"],
            "retryable_value": analysis["retryable_value_inr"],
            "window_days": window_days,
        }
        result.tools_used.append("failed_payment_scan")

        if analysis["failed_payment_count"] == 0:
            # Nothing to recover — emit no fabricated opportunity.
            result.output["decision"] = "NO_FAILED_PAYMENTS"
            result.output["summary"] = (
                f"No failed payments in the last {window_days} days."
            )
            return

        # ── 2. Opportunity, deduped per window bucket ──────────────────────
        bucket = datetime.now(timezone.utc).strftime("%Y%m")
        key = build_opportunity_key(
            merchant_id,
            "payment_recovery",
            f"window:{bucket}",
            window_days,
        )

        # Projected revenue is MEASURED when history supports it, otherwise
        # honestly withheld rather than multiplied by a constant.
        projected = analysis.get("projected_recoverable_inr")
        basis = analysis.get("projection_basis")
        expected_revenue = (
            Decimal(str(round(projected, 2)))
            if projected is not None
            else Decimal(str(analysis["retryable_value_inr"]))
        )
        if projected is None:
            result.output["projection_note"] = (
                "Projected recoverable value is withheld: "
                f"{basis}. The opportunity's expected_revenue therefore "
                "reports the full retryable value as an upper bound, not a "
                "forecast."
            )

        measured = analysis["measured_recovery"]
        confidence = Decimal(str(round(measured["rate"], 3))) if measured.get("rate") is not None else Decimal("0.30")

        scoring = OpportunityScoringEngine().score(
            expected_revenue=float(expected_revenue),
            confidence=confidence,
            evidence_items=2 + min(analysis["failed_payment_count"], 6),
            urgency_score=0.9,
            risk_score=default_risk_for_action_type("retry_payment"),
        )
        opp, created = upsert_opportunity(
            db,
            merchant_id=merchant_id,
            opportunity_key=key,
            type_=OpportunityType.failed_payment_recovery,
            title=(
                f"Recover {analysis['retryable_count']} retryable of "
                f"{analysis['failed_payment_count']} failed payments "
                f"({analysis['retryable_value_inr']:.2f} INR)"
            ),
            confidence=confidence,
            expected_revenue=expected_revenue,
            reasoning=[
                {
                    "basis": "real failed payments classified by failure code",
                    "failed_count": analysis["failed_payment_count"],
                    "retryable_count": analysis["retryable_count"],
                    "retryable_value_inr": analysis["retryable_value_inr"],
                    "needs_customer_action_count": analysis["needs_customer_action_count"],
                    "unknown_classification_count": analysis["unknown_classification_count"],
                },
                {"measured_recovery": measured},
                {"projection_basis": basis},
                {"scoring": scoring.to_dict()},
            ],
        )
        if created:
            result.opportunities_created += 1
        result.output["opportunity_id"] = str(opp.id)

        # ── 3. Simulation, driven by the MEASURED rate ─────────────────────
        rate_for_sim = measured.get("rate")
        sim_recovery_rate = (
            float(rate_for_sim) if rate_for_sim is not None else 0.0
        )
        simulation = SimulationEngine(db).simulate_payment_recovery(
            failed_payment_value=float(analysis["retryable_value_inr"]),
            recovery_rate=sim_recovery_rate,
        )
        SimulationEngine(db).persist(
            simulation,
            merchant_id=merchant_id,
            opportunity_id=opp.id,
            created_by_agent=self.NAME,
            inputs={
                "measured_rate": rate_for_sim,
                "projection_basis": basis,
            },
        )
        result.output["simulation"] = simulation.to_dict()
        result.output["simulation_note"] = (
            "Simulation uses the merchant's MEASURED recovery rate."
            if measured.get("is_usable")
            else "Insufficient history: the simulation uses a 0% rate and is "
                 "deliberately conservative rather than optimistic."
        )
        result.tools_used.append("recovery_simulation")

        # ── 4. Bounded retry proposals, highest value first ────────────────
        if bool(ctx.params.get("propose_retry_action", True)):
            proposed = self._propose_retries(
                db,
                merchant_id=merchant_id,
                analysis=analysis,
                result=result,
            )
            result.output["proposals"] = proposed

        # ── 5. Aggregate handoff to Marketing (no PII) ─────────────────────
        try:
            handoff = handoff_service.request(
                db,
                merchant_id=merchant_id,
                source_agent=self.NAME,
                destination_agent="CampaignStrategistAgent",
                task=(
                    "Design an approved reminder for retryable failed payments "
                    "and a customer-action prompt for failures needing a card update."
                ),
                payload=PaymentRecoveryService(db).marketing_handoff_payload(analysis),
                correlation_id=ctx.params.get("orchestrator_run_id"),
            )
            result.output["marketing_handoff"] = {
                "handoff_id": handoff["handoff_id"],
                "status": handoff["status"],
            }
        except Exception as exc:
            # Collaboration must never break recovery analysis.
            result.errors.append(f"marketing_handoff_skipped: {type(exc).__name__}")

        result.output["summary"] = (
            f"{analysis['retryable_count']} of {analysis['failed_payment_count']} "
            f"failed payments are retryable "
            f"({analysis['needs_customer_action_count']} need customer action). "
            f"Measured recovery rate: "
            + (
                f"{measured['rate']:.0%} over {measured['resolved_failures']} failures."
                if measured.get("rate") is not None
                else "unavailable (insufficient history)."
            )
        )

    # ── helpers ──────────────────────────────────────────────────────────

    def _propose_retries(
        self,
        db: Session,
        *,
        merchant_id: uuid.UUID,
        analysis: dict[str, Any],
        result: AgentResult,
    ) -> list[dict[str, Any]]:
        """Propose bounded retries for genuinely retryable, not-already-proposed payments."""
        assert_permission(self.NAME, PROPOSE_ACTION)

        already = self._proposed_payment_keys(db, merchant_id)
        proposed: list[dict[str, Any]] = []
        limit = int(analysis.get("max_proposals", MAX_PROPOSALS))

        for candidate in analysis["candidates"]:
            if len(proposed) >= limit:
                break
            if not candidate["retryable"]:
                continue
            payment_id = candidate["payment_id"]
            if payment_id in already:
                continue
            action = create_action(
                db,
                merchant_id=merchant_id,
                action_type="retry_payment",
                input_payload={
                    "payment_id": payment_id,
                    "metadata": {
                        "internal_payment_id": payment_id,
                        "order_id": candidate["order_id"],
                        "amount_inr": candidate["amount_inr"],
                        "failure_code": candidate["failure_code"],
                        "failure_classification": candidate["classification"],
                        "attempt_plan": candidate["schedule"],
                        "source_agent": self.NAME,
                        "note": (
                            "Proposed by PaymentRecoveryAgent from a verified "
                            "failure classification. Execution stays disabled "
                            "until RAZORPAY_ENABLED is explicitly enabled; "
                            "approval is human-only."
                        ),
                    },
                },
                requested_by=f"agent:{self.NAME}",
            )
            already.add(payment_id)
            proposed.append(
                {
                    "action_id": str(action.id),
                    "status": str(action.status),
                    "payment_id": payment_id,
                    "amount_inr": candidate["amount_inr"],
                    "classification": candidate["classification"],
                }
            )
            result.actions_proposed += 1

        result.tools_used.append("phase4_propose")
        skipped_existing = sum(
            1
            for c in analysis["candidates"]
            if c["retryable"] and c["payment_id"] in already and
            not any(p["payment_id"] == c["payment_id"] for p in proposed)
        )
        result.output["duplicate_proposals_skipped"] = skipped_existing
        return proposed

    @staticmethod
    def _proposed_payment_keys(db: Session, merchant_id: uuid.UUID) -> set[str]:
        """
        Payment ids this merchant already has an open/completed retry for.

        Scoped to the merchant: without that filter one workspace's in-flight
        retry would suppress another workspace's proposal.
        """
        rows = db.scalars(
            select(AgentAction).where(
                AgentAction.merchant_id == merchant_id,
                AgentAction.action_type == "retry_payment",
                AgentAction.status.in_(list(_OPEN_RETRY_STATUSES)),
            )
        ).all()
        keys: set[str] = set()
        for action in rows:
            meta = (action.input_payload or {}).get("metadata") or {}
            pid = meta.get("internal_payment_id")
            if pid:
                keys.add(str(pid))
        return keys