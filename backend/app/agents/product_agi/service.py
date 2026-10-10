"""Product Agent read model — assembles the dashboard from real data.

This module is the ONLY place that decides what the /product-agent page
sees. Three rules govern every field:

  1. A number is rendered only when it was measured. An unavailable metric
     is ``null`` with a stated reason, never a plausible substitute.
  2. Activity comes from persisted ``product_agent_events`` rows and
     nothing else.
  3. Platform connection status is derived from the actual connection
     rows / payment records. A platform with no integration implemented is
     reported ``not_connected`` forever — the UI does not get to imply
     otherwise.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.agents.product_agi.state import (
    IMPACT_PENDING_REASON,
    PROGRESS_STEPS,
    RunStatus,
    Stage,
    stage_index,
)
from backend.app.models.agent_action import AgentAction
from backend.app.models.enums import AgentActionStatus
from backend.app.models.payment import Payment
from backend.app.models.product_agi import (
    ProductAgentEvent,
    ProductAgentFinding,
    ProductAgentRecommendation,
    ProductAgentRun,
)
from backend.app.services import product_intelligence as pi
from backend.app.services.marketing_action_sync import approval_state_for
from backend.app.services.product_action_sync import (
    RUN_LEVEL_STATUSES,
    aggregate_run_state,
)

log = logging.getLogger(__name__)

#: Honest learning copy. The platform does not learn from recommendations
#: that were never approved and executed, so the default says exactly that.
LEARNING_PENDING = (
    "Learning begins after an approved recommendation is executed and produces "
    "a measurable outcome. Nothing has been learned yet."
)

#: Canonical ``agent_actions.status`` values. Anything else in a
#: recommendation's ``status`` is a prepare-time snapshot, not a live state.
CANONICAL_ACTION_STATUSES = frozenset(
    {"requested", "approved", "rejected", "executing", "completed", "failed"}
)

#: Run statuses that exist only AFTER the merchant approved something — the
#: prepare-time ``run.summary`` ("Nothing has been executed") is false for
#: them, so the headline is rebuilt from the canonical counts.
POST_APPROVAL_STATUSES = frozenset(
    {"approved_awaiting_execution", "executing", "completed", "completed_with_failures"}
)


def _iso(value: Any) -> str | None:
    to_iso = getattr(value, "isoformat", None)
    if value is None:
        return None
    try:
        return str(to_iso()) if callable(to_iso) else str(value)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Platform honesty
# ---------------------------------------------------------------------------


def platform_states(db: Session, merchant_id: uuid.UUID) -> list[dict[str, Any]]:
    """Connection state per platform, derived from real records only.

    Razorpay is ``connected`` only when this merchant actually has payments
    attributed to it — a real ingestion, not an env flag. The store is
    ``connected`` because this platform's own catalog IS the storefront
    source of truth the Product Agent reads. Shopify, WooCommerce and Google
    Merchant have no integration in this codebase, so they are permanently
    and honestly ``not_connected``.
    """
    from backend.app.core.config import get_settings

    razorpay_orders = db.scalar(
        select(func.count(Payment.id)).where(
            Payment.merchant_id == merchant_id,
            Payment.provider == "razorpay",
        )
    )
    payment_count = db.scalar(
        select(func.count(Payment.id)).where(Payment.merchant_id == merchant_id)
    )
    razorpay_connected = bool(razorpay_orders)
    env_enabled = bool(get_settings().RAZORPAY_ENABLED)

    return [
        {
            "key": "shopify",
            "name": "Shopify",
            "status": "not_connected",
            "blurb": "No Shopify integration exists on this platform",
            "meta": "No catalog or order data is read from Shopify",
            "integration_implemented": False,
        },
        {
            "key": "google_merchant",
            "name": "Google Merchant",
            "status": "not_connected",
            "blurb": "No Google Merchant Center integration exists",
            "meta": "No product feed is published or synced",
            "integration_implemented": False,
        },
        {
            "key": "woocommerce",
            "name": "WooCommerce",
            "status": "not_connected",
            "blurb": "No WooCommerce integration exists on this platform",
            "meta": "No store data is imported from WooCommerce",
            "integration_implemented": False,
        },
        {
            "key": "razorpay",
            "name": "Razorpay",
            "status": "connected" if razorpay_connected else "not_connected",
            "blurb": (
                f"{int(razorpay_orders or 0)} Razorpay payment record(s) ingested"
                if razorpay_connected
                else "No Razorpay payments recorded for this workspace"
            ),
            "meta": (
                "Payment and settlement data is live"
                if razorpay_connected
                else (
                    "Payments ingest via checkout webhooks"
                    + ("" if env_enabled else " (Razorpay is disabled in this environment)")
                )
            ),
            "integration_implemented": True,
        },
        {
            "key": "storefront",
            "name": "Website / Store",
            "status": "connected",
            "blurb": "This workspace's own catalog is the source of truth",
            "meta": (
                f"{int(payment_count or 0)} payment record(s) in this workspace"
            ),
            "integration_implemented": True,
        },
    ]


# ---------------------------------------------------------------------------
# Run / finding / recommendation lookups (all tenant-scoped in SQL)
# ---------------------------------------------------------------------------


def latest_run(
    db: Session, merchant_id: uuid.UUID
) -> ProductAgentRun | None:
    stmt = (
        select(ProductAgentRun)
        .where(ProductAgentRun.merchant_id == merchant_id)
        .order_by(ProductAgentRun.created_at.desc())
        .limit(1)
    )
    return db.scalars(stmt).first()


def get_run(db: Session, merchant_id: uuid.UUID, run_id: str) -> ProductAgentRun | None:
    try:
        rid = uuid.UUID(str(run_id))
    except (TypeError, ValueError):
        return None
    run = db.get(ProductAgentRun, rid)
    if run is None or run.merchant_id != merchant_id:
        return None
    return run


def list_runs(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    limit: int = 20,
    analysis_cycle_id: str | None = None,
) -> list[ProductAgentRun]:
    """Run history for one tenant, newest first.

    ``analysis_cycle_id`` narrows to a single shared AI Team analysis
    cycle. The merchant filter is applied unconditionally, so a cycle id
    belonging to another tenant can never surface their runs.
    """
    stmt = select(ProductAgentRun).where(ProductAgentRun.merchant_id == merchant_id)
    if analysis_cycle_id:
        stmt = stmt.where(ProductAgentRun.analysis_cycle_id == analysis_cycle_id)
    stmt = stmt.order_by(ProductAgentRun.created_at.desc()).limit(
        max(1, min(int(limit), 100))
    )
    return list(db.scalars(stmt).all())


def cycle_run(
    db: Session, merchant_id: uuid.UUID, cycle_id: str
) -> ProductAgentRun | None:
    """The one Product Agent run belonging to ``cycle_id`` for this tenant.

    Returns None when the cycle produced no Product Agent run — used by
    the AI Team page and the Product Agent dashboard to detect a cycle in
    which the Product Agent was not (yet) dispatched.
    """
    if not cycle_id:
        return None
    return db.scalars(
        select(ProductAgentRun)
        .where(
            ProductAgentRun.merchant_id == merchant_id,
            ProductAgentRun.analysis_cycle_id == cycle_id,
        )
        .order_by(ProductAgentRun.created_at.desc())
        .limit(1)
    ).first()


def active_run(db: Session, merchant_id: uuid.UUID) -> ProductAgentRun | None:
    """The in-flight run for this tenant, if any.

    Used as the idempotency guard: while a Product Agent run is queued or
    running (including one dispatched by a shared AI Team cycle), a second
    dispatch must join it instead of creating a duplicate.
    """
    return db.scalars(
        select(ProductAgentRun)
        .where(
            ProductAgentRun.merchant_id == merchant_id,
            ProductAgentRun.status.in_(("queued", "running")),
        )
        .order_by(ProductAgentRun.created_at.desc())
        .limit(1)
    ).first()


def findings_for_run(
    db: Session, merchant_id: uuid.UUID, run_id: str
) -> list[ProductAgentFinding]:
    run = get_run(db, merchant_id, run_id)
    if run is None:
        return []
    stmt = (
        select(ProductAgentFinding)
        .where(
            ProductAgentFinding.run_id == run.id,
            ProductAgentFinding.merchant_id == merchant_id,
        )
        .order_by(ProductAgentFinding.created_at.asc())
    )
    return list(db.scalars(stmt).all())


def _live_action(db: Session, merchant_id: uuid.UUID, action_id: Any) -> AgentAction | None:
    if not action_id:
        return None
    try:
        aid = uuid.UUID(str(action_id))
    except (TypeError, ValueError):
        return None
    action = db.get(AgentAction, aid)
    if action is None or action.merchant_id != merchant_id:
        return None
    return action


def recommendations_for_run(
    db: Session, merchant_id: uuid.UUID, run_id: str
) -> list[ProductAgentRecommendation]:
    run = get_run(db, merchant_id, run_id)
    if run is None:
        return []
    stmt = (
        select(ProductAgentRecommendation)
        .where(
            ProductAgentRecommendation.run_id == run.id,
            ProductAgentRecommendation.merchant_id == merchant_id,
        )
        .order_by(ProductAgentRecommendation.created_at.asc())
    )
    return list(db.scalars(stmt).all())


def serialize_finding(row: ProductAgentFinding) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "run_id": str(row.run_id),
        "type": row.type,
        "title": row.title,
        "description": row.description,
        "severity": row.severity,
        "confidence": row.confidence,
        "evidence": row.evidence or [],
        "product_ids": row.product_ids or [],
        "data": row.data or {},
        "created_at": _iso(row.created_at),
    }


def serialize_recommendation(
    db: Session, merchant_id: uuid.UUID, row: ProductAgentRecommendation
) -> dict[str, Any]:
    """Serialize a recommendation with its LIVE action state overlaid.

    The stored status is a prepare-time snapshot; the canonical
    ``agent_actions`` row is the truth for approval, so it is always read
    fresh and tenant-verified.
    """
    action = _live_action(db, merchant_id, row.action_id)
    live_status = str(getattr(action.status, "value", action.status)) if action else None
    approval_state = approval_state_for(live_status) if live_status else None
    executed = live_status == AgentActionStatus.completed.value
    return {
        "id": str(row.id),
        "run_id": str(row.run_id),
        "type": row.type,
        "title": row.title,
        "problem": row.problem,
        "recommendation": row.recommendation,
        "why_now": row.why_now,
        "confidence": float(row.confidence or 0.0),
        "evidence": row.evidence or [],
        "expected_impact": row.expected_impact
        or {"status": "unavailable", "text": IMPACT_PENDING_REASON},
        "risk": row.risk,
        "affected_products": row.affected_products or [],
        "basis": row.basis,
        "action_required": bool(row.action_required),
        "approval_required": bool(row.approval_required),
        "status": live_status or row.status,
        "approval_state": approval_state,
        "executed": executed,
        "action_id": str(row.action_id) if row.action_id else None,
        "data": row.data or {},
        "created_at": _iso(row.created_at),
    }


# ---------------------------------------------------------------------------
# Catalog view for the product tables / preview tabs
# ---------------------------------------------------------------------------


def catalog_view(
    db: Session, merchant_id: uuid.UUID, *, window_days: int = 90
) -> dict[str, Any]:
    """Real product rows plus the four preview segments, from one snapshot."""
    snapshot = pi.build_snapshot(
        db, merchant_id, window_days=window_days
    )
    performance = pi.product_performance(snapshot, limit=10)
    under = pi.underperforming_products(snapshot)
    inventory = pi.low_stock_risk(snapshot)
    content = pi.content_gaps(snapshot)
    health = pi.catalog_health(snapshot, content=content, inventory=inventory)
    opportunities = pi.product_opportunities(db, merchant_id, snapshot)

    status_by_id: dict[str, dict[str, Any]] = {}
    for row in performance["all_products"]:
        status_by_id[row["product_id"]] = row

    under_ids = {r["product_id"] for r in under.get("underperforming") or []}
    low_ids = {r["product_id"] for r in inventory.get("risks") or []}
    opp_ids: list[str] = []
    for item in opportunities.get("opportunities") or []:
        for pid in item.get("product_ids") or []:
            if pid not in opp_ids:
                opp_ids.append(str(pid))

    def _row(product: dict[str, Any]) -> dict[str, Any]:
        perf = status_by_id.get(product["product_id"], {})
        return {
            "product_id": product["product_id"],
            "name": product["name"],
            "sku": product["sku"],
            "category": product["category"],
            "price_inr": product["price_inr"],
            "stock_quantity": product["stock_quantity"],
            "units_sold": product["units_sold"],
            "revenue_inr": product["revenue_inr"],
            "orders": product["orders"],
            "trend_pct": product["trend_pct"],
            "revenue_share_pct": perf.get("revenue_share_pct"),
            "status": perf.get("status") or "unavailable",
            "low_stock": product["low_stock"],
        }

    all_rows = [_row(p) for p in snapshot.products]
    return {
        "window_days": int(window_days),
        "generated_at": _iso(snapshot.generated_at),
        "summary": snapshot.summary(),
        "catalog_health": health,
        "products": all_rows,
        "segments": {
            "top": [
                r for r in all_rows if r["product_id"]
                in {t["product_id"] for t in performance["top_products"]}
            ],
            "underperforming": [r for r in all_rows if r["product_id"] in under_ids],
            "low_stock": [r for r in all_rows if r["product_id"] in low_ids],
            "opportunities": [
                r for r in all_rows if r["product_id"] in set(opp_ids)
            ],
        },
        "segment_status": {
            "underperforming": under.get("status"),
            "underperforming_reason": under.get("reason"),
            "bundles": opportunities.get("bundles", {}).get("status"),
            "bundles_reason": opportunities.get("bundles", {}).get("reason"),
            "pricing_competitor": opportunities.get("pricing", {})
            .get("competitor_pricing", {})
            .get("status"),
        },
    }


# ---------------------------------------------------------------------------
# Dashboard status payload
# ---------------------------------------------------------------------------


def run_duration_seconds(run: ProductAgentRun) -> float | None:
    if run.started_at is None:
        return None
    end = run.completed_at
    if end is None:
        return None
    return round((end - run.started_at).total_seconds(), 1)


# ---------------------------------------------------------------------------
# Canonical action state → run state (the ONE mapping)
# ---------------------------------------------------------------------------


def _action_state_key(rec: dict[str, Any]) -> str:
    """Counting key for one linked action record.

    Prefers the canonical ``approval_state`` overlay and falls back to the
    live ``status``; a rec that proves execution counts as executed, and
    anything unresolved counts as awaiting approval — never the reverse.
    """
    by_approval_state = {
        "REQUIRED": "awaiting_approval",
        "APPROVED": "approved",
        "EXECUTING": "executing",
        "COMPLETED": "executed",
        "FAILED": "failed",
        "REJECTED": "rejected",
    }
    state = rec.get("approval_state")
    if state in by_approval_state:
        return by_approval_state[state]
    by_status = {
        "requested": "awaiting_approval",
        "awaiting_approval": "awaiting_approval",
        "proposed": "awaiting_approval",
        "approved": "approved",
        "executing": "executing",
        "completed": "executed",
        "executed": "executed",
        "failed": "failed",
        "rejected": "rejected",
    }
    status = rec.get("status")
    if status in by_status:
        return by_status[status]
    if rec.get("executed"):
        return "executed"
    return "awaiting_approval"


def empty_action_counts() -> dict[str, int]:
    return {
        "total": 0,
        "awaiting_approval": 0,
        "approved": 0,
        "executing": 0,
        "executed": 0,
        "rejected": 0,
        "failed": 0,
    }


def action_counts(recommendations: list[dict[str, Any]]) -> dict[str, int]:
    """Live counts of the run's linked ``agent_actions`` records.

    Counted from the canonical action rows the recommendations carry, never
    from the recommendation count itself: a recommendation without an action
    is not an approval, and an approved action is not an executed one.
    """
    counts = empty_action_counts()
    for rec in recommendations:
        if not rec.get("action_id"):
            continue
        counts["total"] += 1
        counts[_action_state_key(rec)] += 1
    return counts


def live_action_statuses(recommendations: list[dict[str, Any]]) -> list[str]:
    """Canonical ``agent_actions.status`` behind each linked recommendation.

    ``serialize_recommendation`` overlays the LIVE action row, so a resolved
    action always reports its true canonical status. A linked action that no
    longer resolves (deleted, or outside the tenant) has no evidence of
    completion, so it counts as ``requested`` — unresolved work is never
    reported as done. Previously a stale ``"executed"`` snapshot on an
    unresolvable row was read as ``completed``, which let a run with no
    surviving action claim it had finished successfully.
    """
    statuses: list[str] = []
    for rec in recommendations:
        if not rec.get("action_id"):
            continue
        status = rec.get("status")
        if status in CANONICAL_ACTION_STATUSES:
            statuses.append(str(status))
        else:
            # Includes the prepare-time snapshot vocabulary ("proposed",
            # "awaiting_approval") and an unresolvable row's stale mirror —
            # none of which is evidence that work completed.
            statuses.append("requested")
    return statuses


def effective_run_state(
    run: ProductAgentRun, recommendations: list[dict[str, Any]] | None = None
) -> tuple[str, str, str]:
    """(status, stage, approval_status) the API reports for this run.

    ``product_agent_runs`` is a MIRROR of ``agent_actions`` (see
    ``services/product_action_sync.py``). When the mirror lags — a run
    parked by a build that predated the mirror, or a transition written
    outside the sync — the canonical action rows win, so the API can never
    answer ``waiting_approval`` for a run whose actions already executed.

    A run-level outcome (failed / blocked / cancelled) is never
    overwritten: it is decided by the run itself, not by its actions.
    """
    if run.status in RUN_LEVEL_STATUSES:
        return run.status, run.current_stage, run.approval_status
    aggregate = aggregate_run_state(live_action_statuses(recommendations or []))
    if aggregate is None:
        return run.status, run.current_stage, run.approval_status
    return aggregate


def build_status(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    window_days: int | None = None,
) -> dict[str, Any]:
    """The complete /product-agent status payload.

    ``window_days`` defaults to the window the latest run actually measured,
    so the dashboard can never silently describe a different period than the
    run it is showing. Falls back to 90 days when there is no run yet.

    Never raises for missing data: an empty workspace returns a fully
    populated payload whose values are honest zeros / nulls with reasons.
    """
    run = latest_run(db, merchant_id)
    if window_days is None:
        configured = (run.state or {}).get("window_days") if run else None
        if not isinstance(configured, int) or not (1 <= configured <= 365):
            configured = 90
        window_days = configured
    snapshot = pi.build_snapshot(
        db, merchant_id, window_days=window_days
    )
    summary = snapshot.summary()
    view = catalog_view(db, merchant_id, window_days=window_days)

    insights = _insights(db, merchant_id, summary, view, snapshot)
    platforms = platform_states(db, merchant_id)

    if run is None:
        return {
            "has_run": False,
            "run_id": None,
            "analysis_cycle_id": None,
            "managed_by_ai_team": True,
            "headline": (
                "No Product Agent run yet. Start one to analyse this workspace's "
                "real catalog, demand and inventory."
            ),
            "support": (
                f"This workspace has {summary['product_count']} product(s), "
                f"{summary['total_units']} unit(s) on hand across "
                f"{summary['category_count']} categor(ies)."
            ),
            "status_label": "No run yet",
            "needs_approval": False,
            "approval_status": None,
            "action_counts": empty_action_counts(),
            "step_index": -1,
            "stage": None,
            "status": None,
            "insights": insights,
            "recommendations": [],
            "work": [],
            "activity": [],
            "learning_insight": LEARNING_PENDING,
            "platforms": platforms,
            "metrics": summary,
            "catalog": view,
            "workflow_steps": [{"top": t, "bottom": b} for t, b in PROGRESS_STEPS],
        }

    recommendations = [
        serialize_recommendation(db, merchant_id, r)
        for r in recommendations_for_run(db, merchant_id, str(run.id))
    ]
    events = (
        db.scalars(
            select(ProductAgentEvent)
            .where(
                ProductAgentEvent.run_id == run.id,
                ProductAgentEvent.merchant_id == merchant_id,
            )
            .order_by(ProductAgentEvent.seq.asc())
        )
        .all()
    )
    metrics = dict(run.metrics or {})
    metrics.setdefault("product_count", summary["product_count"])
    # One authoritative state model: the stored run row is a mirror, the
    # canonical agent_actions rows decide what the dashboard shows (§11).
    status_value, stage_value, approval_value = effective_run_state(
        run, recommendations
    )
    counts = action_counts(recommendations)
    needs_approval = counts["awaiting_approval"] > 0
    metrics["executed_count"] = counts["executed"]
    metrics["action_count"] = counts["total"]

    return {
        "has_run": True,
        "run_id": str(run.id),
        "analysis_cycle_id": run.analysis_cycle_id,
        "managed_by_ai_team": True,
        "status": status_value,
        "stage": stage_value,
        "step_index": stage_index(stage_value),
        "status_label": _status_label(status_value, approval_value),
        "needs_approval": needs_approval,
        "approval_status": approval_value,
        "action_counts": counts,
        "headline": _headline(run, status_value, metrics, counts),
        "support": _support_text(run, metrics, recommendations, status_value),
        "llm": {
            "provider": run.llm_provider,
            "model": run.llm_model,
            "degraded": bool((run.state or {}).get("llm_degraded")),
        },
        "insights": insights,
        "recommendations": recommendations,
        "work": _work_items(run, recommendations),
        "activity": [_activity(e) for e in reversed(events)][:40],
        "learning_insight": _learning_text(db, merchant_id, run),
        "platforms": platforms,
        "metrics": metrics,
        "catalog": view,
        "verification": (run.state or {}).get("verification"),
        "knowledge_gaps": (run.state or {}).get("knowledge_gaps") or [],
        "started_at": _iso(run.started_at),
        "completed_at": _iso(run.completed_at),
        "duration_seconds": run_duration_seconds(run),
        "workflow_steps": [{"top": t, "bottom": b} for t, b in PROGRESS_STEPS],
        "result": run.result,
        "errors": run.errors or [],
    }


def _headline(
    run: ProductAgentRun,
    status_value: str,
    metrics: dict[str, Any],
    counts: dict[str, int],
) -> str:
    """Headline sentence for the status card.

    ``run.summary`` is written once, when the agent parks for approval, and
    it ends with "Nothing has been executed." — true at that moment, false
    the moment a human approves. After approval the headline is rebuilt from
    the canonical action counts, so the card can never carry two opposite
    statements at once.
    """
    snapshot = run.summary or "Run in progress."
    if status_value not in POST_APPROVAL_STATUSES:
        return snapshot

    facts: list[str] = []
    if metrics.get("product_count") is not None:
        facts.append(f"Analysed {metrics['product_count']} product(s)")
    if metrics.get("opportunity_count"):
        facts.append(f"found {metrics['opportunity_count']} opportunity(ies)")
    if metrics.get("recommendation_count"):
        facts.append(f"prepared {metrics['recommendation_count']} recommendation(s)")
    if not facts:
        return snapshot
    head = ", ".join(facts) + "."
    return f"{head} {_outcome_tail(counts)}"


def _status_label(status: str | None, approval_status: str | None) -> str:
    if status == RunStatus.waiting_approval.value:
        return "Waiting for your approval"
    if status == RunStatus.approved_awaiting_execution.value:
        return "Approved — awaiting execution"
    if status == RunStatus.executing.value:
        return "Executing approved actions"
    if status == RunStatus.running.value:
        return "Analysing your products"
    if status == RunStatus.queued.value:
        return "Queued"
    if status == RunStatus.completed.value:
        return "Completed"
    if status == RunStatus.completed_with_failures.value:
        return "Completed with failures"
    if status == RunStatus.failed.value:
        return "Last run failed"
    if status == RunStatus.blocked.value:
        return "Last run blocked by safety review"
    if status == RunStatus.completed_no_actions.value:
        return "Analysis complete — nothing needs approval"
    if status == RunStatus.cancelled.value:
        return "Last run cancelled"
    return "Idle"


def _outcome_tail(counts: dict[str, int]) -> str:
    """What actually happened to the run's actions — canonical counts only."""
    if not counts["total"]:
        return "No action required approval, so no action was created."
    if (
        counts["awaiting_approval"]
        and not counts["approved"]
        and not counts["executing"]
        and not counts["executed"]
        and not counts["failed"]
        and not counts["rejected"]
    ):
        return (
            "Nothing has been executed — every recommendation waits for your "
            "approval."
        )
    segs: list[str] = []
    if counts["awaiting_approval"]:
        segs.append(f"{counts['awaiting_approval']} action(s) awaiting your approval")
    if counts["approved"] or counts["executing"]:
        segs.append(
            f"{counts['approved'] + counts['executing']} action(s) approved, "
            "not yet executed"
        )
    if counts["executed"]:
        segs.append(
            f"{counts['executed']} action(s) approved and executed through the "
            "actions pipeline"
        )
    if counts["rejected"]:
        segs.append(f"{counts['rejected']} action(s) rejected by you")
    if counts["failed"]:
        segs.append(f"{counts['failed']} action(s) failed")
    return "; ".join(segs) + "."


def _support_text(
    run: ProductAgentRun,
    metrics: dict[str, Any],
    recommendations: list[dict[str, Any]] | None = None,
    status_value: str | None = None,
) -> str:
    """One honest sentence about what happened.

    The execution wording is derived from the LIVE action states, not from
    the run's prepare-time snapshot — otherwise the dashboard would keep
    claiming "nothing has been executed" after a human approved and executed
    an action.
    """
    if status_value in ("queued", "running"):
        return (
            f"Analysing {metrics.get('product_count', 0)} product(s) in this "
            "workspace. Result counts are finalised when the run finishes."
        )

    parts: list[str] = []
    if metrics.get("product_count") is not None:
        parts.append(f"{metrics['product_count']} products analysed")
    if metrics.get("opportunity_count"):
        parts.append(f"{metrics['opportunity_count']} opportunities found")
    if metrics.get("recommendation_count"):
        parts.append(f"{metrics['recommendation_count']} recommendations prepared")
    if not parts:
        return "The run has not produced a summary yet."

    tail = _outcome_tail(action_counts(recommendations or []))
    return f"Analysis complete: {'; '.join(parts)}. {tail}"


def _insights(
    db: Session,
    merchant_id: uuid.UUID,
    summary: dict[str, Any],
    view: dict[str, Any],
    snapshot: pi.CatalogSnapshot,
) -> list[dict[str, Any]]:
    """Real finding counts. Every entry is derived, never decorative."""
    performance = pi.product_performance(snapshot, limit=10)
    under = pi.underperforming_products(snapshot)
    content = pi.content_gaps(snapshot)
    inventory = pi.low_stock_risk(snapshot)
    pricing = pi.pricing_opportunities(snapshot)
    # Same window as the rest of the read model, so the bundle reason can
    # never describe a different period than the summary above it.
    bundles = pi.bundle_opportunities(
        db, merchant_id, snapshot, window_days=snapshot.window_days
    )

    demand_products = sum(
        1 for p in snapshot.products if int(p["units_sold"]) > 0
    )
    out: list[dict[str, Any]] = [
        {
            "id": "top_sellers",
            "icon": "chart",
            "value": f"{demand_products} product(s) with recorded demand",
            "detail": (
                f"Best performer: {performance['top_products'][0]['name']} "
                f"({performance['top_products'][0]['units_sold']} unit(s))"
                if demand_products
                else f"No settled demand in the last {summary['window_days']} days"
            ),
        },
        {
            "id": "never_sold",
            "icon": "alert",
            "value": f"{summary['never_sold_count']} product(s) never sold",
            "detail": (
                f"Zero settled units in the last {summary['window_days']} days"
            ),
        },
        {
            "id": "low_stock",
            "icon": "box",
            "value": f"{summary['low_stock_count']} low-stock product(s)",
            "detail": (
                f"Threshold {summary['low_stock_threshold']} units, or projected "
                f"demand above stock over {inventory.get('projection_days')} days"
            ),
        },
        {
            "id": "content",
            "icon": "doc",
            "value": f"{content.get('gap_count', 0)} product(s) with content gaps",
            "detail": (
                f"{content.get('completeness_pct', 0)}% of catalog content is complete"
            ),
        },
        {
            "id": "opportunities",
            "icon": "git-branch",
            "value": f"{summary_opportunity_count(view)} product(s) with an opportunity",
            "detail": "Computed from real catalog, demand and inventory data",
        },
        {
            "id": "underperforming",
            "icon": "search-check",
            "value": (
                f"{len(under.get('underperforming') or [])} underperforming product(s)"
                if under.get("status") == "available"
                else "Underperformance: insufficient data"
            ),
            "detail": str(under.get("reason") or under.get("method") or ""),
        },
        {
            "id": "pricing",
            "icon": "target",
            "value": f"{pricing.get('opportunity_count', 0)} internal pricing signal(s)",
            "detail": (
                "Competitor pricing unavailable — "
                + str(pricing.get("competitor_pricing", {}).get("reason", ""))
            ),
        },
        {
            "id": "bundles",
            "icon": "branch",
            "value": (
                f"{bundles.get('count', 0)} bundle candidate(s)"
                if bundles.get("status") == "available"
                else "Bundles: insufficient data"
            ),
            "detail": str(bundles.get("reason") or bundles.get("impact", {}).get("reason") or ""),
        },
    ]
    return out


def summary_opportunity_count(view: dict[str, Any]) -> int:
    return len(view["segments"]["opportunities"])


def _work_items(
    run: ProductAgentRun, recommendations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Real lifecycle rows for the Recent Activity panel."""
    metrics = dict(run.metrics or {})
    counts = action_counts(recommendations)
    required = counts["awaiting_approval"]
    approved = counts["approved"] + counts["executing"]
    executed = counts["executed"]
    rejected = counts["rejected"]
    failed = counts["failed"]

    items: list[dict[str, Any]] = []
    if metrics.get("product_count") is not None:
        items.append(
            {
                "id": "catalog",
                "title": "Catalog analysis",
                "state": "completed",
                "meta": f"{metrics.get('product_count')} products read from this workspace",
            }
        )
    if metrics.get("total_units_sold") is not None:
        items.append(
            {
                "id": "performance",
                "title": "Product performance analysis",
                "state": "completed",
                "meta": (
                    f"{metrics.get('total_units_sold')} unit(s), INR "
                    f"{metrics.get('total_revenue_inr')} revenue in the window"
                ),
            }
        )
    if metrics.get("opportunity_count"):
        items.append(
            {
                "id": "opportunities",
                "title": "Opportunity detection",
                "state": "completed",
                "meta": f"{metrics.get('opportunity_count')} opportunity(ies) found",
            }
        )
    items.append(
        {
            "id": "recommendations",
            "title": "Recommendation preparation",
            "state": "completed" if metrics.get("recommendation_count") else "completed",
            "meta": f"{metrics.get('recommendation_count', 0)} recommendation(s) prepared",
        }
    )
    if required:
        items.append(
            {
                "id": "approval",
                "title": "Approval required",
                "state": "waiting_approval",
                "meta": f"{required} action(s) awaiting your decision",
            }
        )
    if approved:
        items.append(
            {
                "id": "approved",
                "title": "Approved by you",
                "state": "approved",
                "meta": f"{approved} action(s) approved, not yet executed",
            }
        )
    if executed:
        items.append(
            {
                "id": "executed",
                "title": "Executed actions",
                "state": "completed",
                "meta": f"{executed} action(s) executed through the actions pipeline",
            }
        )
    if rejected:
        items.append(
            {
                "id": "rejected",
                "title": "Rejected by you",
                "state": "rejected",
                "meta": f"{rejected} action(s) rejected — never executed",
            }
        )
    if failed:
        items.append(
            {
                "id": "failed",
                "title": "Failed actions",
                "state": "failed",
                "meta": f"{failed} action(s) failed during execution",
            }
        )
    return items


def _activity(event: ProductAgentEvent) -> dict[str, Any]:
    state = "completed"
    if event.event_type in {"tool_failed", "llm_unavailable", "verification_failed"}:
        state = "failed"
    elif event.event_type == "mcp_tool_call" and (event.data or {}).get("status") not in (
        "success",
        None,
    ):
        state = "failed"
    return {
        "id": str(event.id),
        "title": event.message,
        "time": _iso(event.created_at),
        "state": state,
        "stage": event.stage,
        "event_type": event.event_type,
        "seq": event.seq,
    }


def _learning_text(
    db: Session, merchant_id: uuid.UUID, run: ProductAgentRun
) -> str:
    """Only report learning that actually exists in the database."""
    prepared = 0
    decided = 0
    approved = 0
    executed = 0
    for row in recommendations_for_run(db, merchant_id, str(run.id)):
        prepared += 1
        action = _live_action(db, merchant_id, row.action_id)
        if action is None:
            continue
        status = str(getattr(action.status, "value", action.status))
        if status == AgentActionStatus.completed.value:
            executed += 1
            approved += 1
            decided += 1
        elif status in (
            AgentActionStatus.approved.value,
            AgentActionStatus.executing.value,
            AgentActionStatus.failed.value,
        ):
            approved += 1
            decided += 1
        elif status == AgentActionStatus.rejected.value:
            decided += 1
    if not executed:
        counts = f"{prepared} recommendation(s) prepared; {decided} decision(s) recorded; none executed yet."
        return f"{counts} {LEARNING_PENDING}"
    return (
        f"{prepared} recommendation(s) prepared; {approved} action(s) approved; "
        f"{executed} executed. Outcome measurement has not been recorded yet — "
        "execution results live in the per-action audit trail."
    )


__all__ = [
    "LEARNING_PENDING",
    "action_counts",
    "build_status",
    "catalog_view",
    "effective_run_state",
    "empty_action_counts",
    "findings_for_run",
    "get_run",
    "latest_run",
    "list_runs",
    "live_action_statuses",
    "platform_states",
    "recommendations_for_run",
    "run_duration_seconds",
    "serialize_finding",
    "serialize_recommendation",
]