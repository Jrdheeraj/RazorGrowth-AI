"""
PaymentRecoveryAgent — Phase 5 Feature 6.

Detects failed payments (count, value, repeat failures) from real rows,
creates a failed_payment_recovery opportunity, simulates the recovery
scenario, and MAY propose exactly one retry_payment Phase 4 action per
run for the highest-value failure.

Safety:
  - proposals enter 'requested' state; approval is human-only;
  - real Razorpay execution stays disabled by default (RAZORPAY_ENABLED=false)
    and the Phase 4 executor refuses honestly when disabled;
  - no fake success is ever recorded.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.agents.base import AgentContext, AgentResult, BaseGrowthAgent
from backend.app.agents.permissions import (
    AGENT_PERMISSIONS,
    PROPOSE_ACTION,
    READ_PAYMENTS,
    assert_permission,
)
from backend.app.models.enums import OpportunityType, PaymentStatus
from backend.app.models.opportunity import GrowthOpportunity
from backend.app.models.payment import Payment
from backend.app.services.action_service import create_action
from backend.app.services.memory import GrowthMemoryService
from backend.app.services.opportunity_upsert import (
    build_opportunity_key,
    upsert_opportunity,
)
from backend.app.services.scoring import (
    OpportunityScoringEngine,
    default_risk_for_action_type,
)

log = logging.getLogger(__name__)

RECOVERY_WINDOW_DAYS = 30
DEFAULT_RECOVERY_RATE = Decimal("0.25")   # documented assumption, not data


class PaymentRecoveryAgent(BaseGrowthAgent):
    NAME = "PaymentRecoveryAgent"
    DESCRIPTION = (
        "Finds failed and repeatedly-failing payments worth recovering, "
        "quantifies recoverable revenue, and proposes retry actions that "
        "still require human approval."
    )
    PERMISSIONS = AGENT_PERMISSIONS[NAME]
    TOOLS = ("failed_payment_scan", "recovery_simulation", "phase4_propose")

    def _run(self, ctx: AgentContext, result: AgentResult) -> None:
        assert_permission(self.NAME, READ_PAYMENTS)
        db: Session = ctx.db
        merchant_id: uuid.UUID = ctx.merchant_id

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=RECOVERY_WINDOW_DAYS)

        # ── read-only scan of REAL payment rows ──────────────────────────
        t0 = self._now_ms()
        fails = list(
            db.scalars(
                select(Payment)
                .where(Payment.merchant_id == merchant_id)
                .where(Payment.status == PaymentStatus.failed.value)
                .where(Payment.created_at >= cutoff)
                .order_by(Payment.amount.desc())
            ).all()
        )
        result.db_ms += self._since_ms(t0)
        total_value = sum((Decimal(str(p.amount)) for p in fails), Decimal("0"))
        result.output["failed_payments"] = {
            "count": len(fails),
            "total_value": float(total_value),
            "highest_single": float(Decimal(str(fails[0].amount))) if fails else 0.0,
            "window_days": RECOVERY_WINDOW_DAYS,
        }
        result.tools_used.append("failed_payment_scan")
        if not fails:
            return  # nothing to recover — emit no fabricated opportunity

        # ── recovery opportunity (deduplicated) ──────────────────────────
        scoring = OpportunityScoringEngine()
        bucket = now.strftime("%Y%m")
        key = build_opportunity_key(
            merchant_id, "payment_recovery", f"window:{bucket}", RECOVERY_WINDOW_DAYS
        )
        rec_scoring = scoring.score(
            expected_revenue=total_value * DEFAULT_RECOVERY_RATE,
            confidence=Decimal("0.70"),
            evidence_items=2 + min(len(fails), 4),
            urgency_score=0.9,
            risk_score=default_risk_for_action_type("retry_payment"),
        )
        opp, created = upsert_opportunity(
            db,
            merchant_id=merchant_id,
            opportunity_key=key,
            type_=OpportunityType.failed_payment_recovery,
            title=(
                f"Recover ₹{total_value} in {len(fails)} failed payments "
                f"(last {RECOVERY_WINDOW_DAYS} days)"
            ),
            confidence=Decimal("0.70"),
            expected_revenue=(total_value * DEFAULT_RECOVERY_RATE).quantize(Decimal("0.01")),
            reasoning=[
                {
                    "basis": "real failed payments",
                    "count": len(fails),
                    "value": float(total_value),
                    "assumed_recovery_rate": float(DEFAULT_RECOVERY_RATE),
                },
                {"scoring": rec_scoring.to_dict()},
            ],
        )
        if created:
            result.opportunities_created += 1
        result.output["opportunity_id"] = str(opp.id)

        # ── simulation ───────────────────────────────────────────────────
        assert_permission(self.NAME, "simulate")
        from backend.app.services.simulation import SimulationEngine

        sim_engine = SimulationEngine(db)
        simulation = sim_engine.simulate_payment_recovery(
            failed_payment_value=float(total_value),
            recovery_rate=float(DEFAULT_RECOVERY_RATE),
        )
        sim_engine.persist(
            simulation,
            merchant_id=merchant_id,
            opportunity_id=opp.id,
            created_by_agent=self.NAME,
            inputs={"failed_count": len(fails)},
        )
        result.output["simulation"] = simulation.to_dict()

        # ── ONE retry proposal for the highest-value failure ─────────────
        if bool(ctx.params.get("propose_retry_action", True)):
            assert_permission(self.NAME, PROPOSE_ACTION)
            top = fails[0]
            if self._already_proposed(db, str(top.id)):
                result.output["retry_proposal"] = "already_proposed"
            else:
                action = create_action(
                    db,
                    merchant_id=merchant_id,
                    action_type="retry_payment",
                    input_payload={
                        "payment_id": str(top.provider_payment_id or top.id),
                        "metadata": {
                            "internal_payment_id": str(top.id),
                            "amount_inr": float(top.amount),
                            "source_agent": self.NAME,
                            "note": (
                                "Proposed by PaymentRecoveryAgent. Execution "
                                "remains disabled until RAZORPAY_ENABLED is "
                                "explicitly enabled with configured keys."
                            ),
                        },
                    },
                    requested_by=f"agent:{self.NAME}",
                )
                result.actions_proposed += 1
                result.output["retry_proposal"] = {
                    "action_id": str(action.id),
                    "status": str(action.status),
                }

        # ── memory write (Feature 10/11 hook) ────────────────────────────
        memory = GrowthMemoryService(db, embedding_provider=ctx.embedding_provider)
        mem = memory.record(
            merchant_id=merchant_id,
            memory_type="recommendation",
            content=(
                f"PaymentRecoveryAgent proposed retry for highest-value "
                f"failure; {len(fails)} failures worth ₹{total_value} in window."
            ),
            source_type="agent_run",
            source_id=str(opp.id),
            importance=0.7,
        )
        result.memories_written += 1

    # ── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _already_proposed(db: Session, internal_payment_id: str) -> bool:
        from backend.app.models.agent_action import AgentAction

        rows = db.scalars(
            select(AgentAction).where(
                AgentAction.action_type == "retry_payment",
                AgentAction.status.in_(["requested", "approved", "executing", "completed"]),
            )
        ).all()
        for action in rows:
            payload = action.input_payload or {}
            meta = payload.get("metadata") or {}
            if meta.get("internal_payment_id") == internal_payment_id:
                return True
        return False

    @staticmethod
    def _now_ms() -> int:
        import time

        return int(time.perf_counter() * 1000)

    @staticmethod
    def _since_ms(start_ms: int) -> int:
        import time

        return int(time.perf_counter() * 1000) - start_ms
