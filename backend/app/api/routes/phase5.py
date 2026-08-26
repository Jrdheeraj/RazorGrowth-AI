"""Customer intelligence + simulation + experiment + memory + brief routes."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError as PydValidationError
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.schemas.phase5 import (
    ExperimentCreateRequest,
    ExperimentOut,
    ExperimentsResponse,
    GrowthBriefResponse,
    GrowthMemoryResponse,
    MemoryEntryOut,
    SimulationOut,
    SimulationRequest,
    SimulationsResponse,
    CustomerInsightOut,
    CustomerInsightsResponse,
)
from backend.app.services.brief import GrowthBriefService
from backend.app.services.customer_intelligence import CustomerIntelligenceService
from backend.app.services.experiment_service import (
    ExperimentValidationError,
    ExperimentService,
)
from backend.app.services.memory import GrowthMemoryService
from backend.app.services.simulation import (
    SimulationEngine,
    SimulationEngine as _SimEngine,  # noqa: F401 (alias kept for clarity)
    SimulationValidationError,
)

log = logging.getLogger(__name__)

# ── shared helpers ──────────────────────────────────────────────────────────


def _resolve_merchant(db: Session, merchant_id: uuid.UUID | None) -> uuid.UUID:
    if merchant_id is not None:
        from backend.app.models.merchant import Merchant

        if db.get(Merchant, merchant_id) is None:
            raise HTTPException(status_code=404, detail="MERCHANT_NOT_FOUND")
        return merchant_id
    from backend.app.repositories.merchant import MerchantRepository

    merchants = MerchantRepository(db).list_all(limit=1)
    if not merchants:
        raise HTTPException(status_code=404, detail="MERCHANT_NOT_FOUND")
    return merchants[0].id


insights_router = APIRouter(prefix="/customer-insights", tags=["customer-intelligence"])
customer_insights_router = APIRouter(prefix="/customers", tags=["customer-intelligence"])
simulations_router = APIRouter(prefix="/simulations", tags=["simulations"])
experiments_router = APIRouter(prefix="/experiments", tags=["experiments"])
memory_router = APIRouter(prefix="/growth-memory", tags=["growth-memory"])
brief_router = APIRouter(prefix="/growth-brief", tags=["growth-brief"])


# ── customer insights ───────────────────────────────────────────────────────


def _insight_out(i: Any) -> dict[str, Any]:
    return {
        "customer_id": str(i.customer_id),
        "primary_segment": str(getattr(i.primary_segment, "value", i.primary_segment)),
        "segments": i.segments,
        "order_count": i.order_count,
        "lifetime_value": float(i.lifetime_value),
        "avg_order_value": float(i.avg_order_value),
        "recency_days": i.recency_days,
        "payment_success_rate": float(i.payment_success_rate),
        "failed_payment_count": i.failed_payment_count,
        "churn_risk_score": float(i.churn_risk_score),
        "churn_risk_level": str(getattr(i.churn_risk_level, "value", i.churn_risk_level)),
        "churn_reasons": i.churn_reasons,
        "strategy_note": i.strategy_note,
    }


@insights_router.get("", response_model=CustomerInsightsResponse)
def list_customer_insights(
    merchant_id: uuid.UUID | None = None,
    segment: str | None = None,
    refresh: bool = False,
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> Any:
    mid = _resolve_merchant(db, merchant_id)
    if refresh:
        try:
            CustomerIntelligenceService(db).refresh(mid)
            db.commit()
        except Exception:
            db.rollback()
            raise HTTPException(status_code=500, detail="INSIGHT_REFRESH_FAILED")
    rows = CustomerIntelligenceService(db).list_insights(
        mid, segment=segment, limit=limit
    )
    return {
        "merchant_id": str(mid),
        "count": len(rows),
        "insights": [_insight_out(r) for r in rows],
    }


@customer_insights_router.get("/{customer_id}/insights", response_model=CustomerInsightOut)
def get_customer_insight(
    customer_id: str,
    merchant_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
) -> Any:
    mid = _resolve_merchant(db, merchant_id)
    try:
        cid = uuid.UUID(customer_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid customer_id format")
    insight = CustomerIntelligenceService(db).get_customer_insight(mid, cid)
    if insight is None:
        raise HTTPException(status_code=404, detail="INSIGHT_NOT_FOUND")
    return _insight_out(insight)


# ── simulations ─────────────────────────────────────────────────────────────


@simulations_router.get("", response_model=SimulationsResponse)
def list_simulations(
    merchant_id: uuid.UUID | None = None,
    scenario_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> Any:
    from sqlalchemy import select

    from backend.app.models.experiment import Simulation

    mid = _resolve_merchant(db, merchant_id)
    stmt = (
        select(Simulation)
        .where(Simulation.merchant_id == mid)
        .order_by(Simulation.created_at.desc())
        .limit(limit)
    )
    if scenario_type:
        stmt = stmt.where(Simulation.scenario_type == scenario_type)
    rows = list(db.scalars(stmt).all())
    return {
        "merchant_id": str(mid),
        "simulations": [
            {
                "id": str(s.id),
                "scenario_type": s.scenario_type,
                "estimated_revenue": float(s.estimated_revenue),
                "estimated_cost": float(s.estimated_cost),
                "estimated_profit": float(s.estimated_profit),
                "expected_conversion": float(s.expected_conversion),
                "expected_roi": float(s.expected_roi) if s.expected_roi is not None else None,
                "confidence_low": float(s.confidence_low) if s.confidence_low is not None else None,
                "confidence_high": float(s.confidence_high) if s.confidence_high is not None else None,
                "assumptions": s.assumptions,
                "is_estimate": bool(s.is_estimate),
                "created_by_agent": s.created_by_agent,
                "created_at": str(s.created_at),
            }
            for s in rows
        ],
    }


@simulations_router.post("", response_model=SimulationOut, status_code=201)
def create_simulation(request: SimulationRequest, db: Session = Depends(get_db)) -> Any:
    mid = _resolve_merchant(db, request.merchant_id)
    engine = SimulationEngine(db)
    kwargs: dict[str, Any] = {}
    if request.scenario_type == "discount":
        kwargs = dict(
            discount_percentage=request.discount_percentage or 0,
            target_customers=request.target_customers or 0,
            expected_conversion=request.expected_conversion or 0,
            avg_order_value=request.avg_order_value or 0,
        )
    elif request.scenario_type == "campaign":
        kwargs = dict(
            target_customers=request.target_customers or 0,
            expected_conversion=request.expected_conversion or 0,
            avg_order_value=request.avg_order_value or 0,
            cost_per_target=request.cost_per_target or 0,
        )
    elif request.scenario_type == "payment_recovery":
        kwargs = dict(
            failed_payment_value=request.failed_payment_value or 0,
            recovery_rate=request.recovery_rate or 0,
        )
    else:
        raise HTTPException(status_code=422, detail="Unknown scenario_type")

    try:
        result = engine.simulate(request.scenario_type, **kwargs)
    except (SimulationValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    row = engine.persist(
        result,
        merchant_id=mid,
        opportunity_id=request.opportunity_id,
        created_by_agent="api_request",
        inputs=kwargs,
    )
    db.commit()
    return {
        "id": str(row.id),
        "scenario_type": row.scenario_type,
        "estimated_revenue": float(row.estimated_revenue),
        "estimated_cost": float(row.estimated_cost),
        "estimated_profit": float(row.estimated_profit),
        "expected_conversion": float(row.expected_conversion),
        "expected_roi": float(row.expected_roi) if row.expected_roi is not None else None,
        "confidence_low": float(row.confidence_low) if row.confidence_low is not None else None,
        "confidence_high": float(row.confidence_high) if row.confidence_high is not None else None,
        "assumptions": row.assumptions,
        "is_estimate": bool(row.is_estimate),
        "created_by_agent": row.created_by_agent,
        "created_at": str(row.created_at),
    }


# ── experiments ─────────────────────────────────────────────────────────────


@experiments_router.get("", response_model=ExperimentsResponse)
def list_experiments(
    merchant_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
) -> Any:
    mid = _resolve_merchant(db, merchant_id)
    svc = ExperimentService(db)
    out = []
    for exp in svc.list_experiments(mid):
        latest = svc.latest_result(exp)
        out.append(
            {
                "id": str(exp.id),
                "name": exp.name,
                "status": str(getattr(exp.status, "value", exp.status)),
                "hypothesis": exp.hypothesis,
                "control_group": exp.control_group,
                "treatment_group": exp.treatment_group,
                "target_population_size": exp.target_population_size,
                "latest_result": (
                    {
                        "statistical_status": latest.statistical_status,
                        "uplift_percentage": (
                            float(latest.uplift_percentage)
                            if latest.uplift_percentage is not None
                            else None
                        ),
                        "control_size": latest.control_size,
                        "treatment_size": latest.treatment_size,
                    }
                    if latest is not None
                    else None
                ),
            }
        )
    return {"merchant_id": str(mid), "experiments": out}


@experiments_router.post("", response_model=ExperimentOut, status_code=201)
def create_experiment(
    request: ExperimentCreateRequest, db: Session = Depends(get_db)
) -> Any:
    mid = _resolve_merchant(db, request.merchant_id)
    svc = ExperimentService(db)
    try:
        exp = svc.create_experiment(
            merchant_id=mid,
            name=request.name,
            hypothesis=request.hypothesis,
            control_group=request.control_group,
            treatment_group=request.treatment_group,
            target_population_size=request.target_population_size,
        )
        db.commit()
    except ExperimentValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "id": str(exp.id),
        "name": exp.name,
        "status": str(getattr(exp.status, "value", exp.status)),
        "hypothesis": exp.hypothesis,
        "control_group": exp.control_group,
        "treatment_group": exp.treatment_group,
        "target_population_size": exp.target_population_size,
        "latest_result": None,
    }


# ── growth memory ───────────────────────────────────────────────────────────


@memory_router.get("", response_model=GrowthMemoryResponse)
def list_growth_memory(
    merchant_id: uuid.UUID | None = None,
    query: str | None = Query(default=None, max_length=300),
    memory_type: str | None = None,
    k: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Any:
    mid = _resolve_merchant(db, merchant_id)
    svc = GrowthMemoryService(db, embedding_provider=None)
    if query:
        hits = svc.retrieve(mid, query, k=k, memory_type=memory_type)
        entries = [
            {
                "id": h["id"],
                "memory_type": h["memory_type"],
                "content": h["content"],
                "importance": h["importance"],
                "outcome_variance_pct": h["outcome_variance_pct"],
                "created_at": h["created_at"],
            }
            for h in hits
        ]
    else:
        rows = svc.retrieve(mid, "", k=k, memory_type=memory_type)
        entries = rows  # already shaped by retrieve()
    return {"merchant_id": str(mid), "memories": entries}


# ── growth brief ────────────────────────────────────────────────────────────


@brief_router.get("", response_model=GrowthBriefResponse)
def get_growth_brief(
    merchant_id: uuid.UUID | None = None,
    window_days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
) -> Any:
    mid = _resolve_merchant(db, merchant_id)
    brief = GrowthBriefService(db).build(mid, window_days=window_days)
    return brief
