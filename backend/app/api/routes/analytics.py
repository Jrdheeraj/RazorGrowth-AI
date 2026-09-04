"""Analytics API routes — Phase M."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.api.deps import MerchantContext, merchant_ctx
from backend.app.db.session import get_db
from backend.app.schemas.analytics import (
    AnalyticsOverviewResponse,
    RevenueTimeSeriesResponse,
    OrderTimeSeriesResponse,
    CustomerTimeSeriesResponse,
    AnalyticsTransactionsResponse,
    AnalyticsCustomersResponse,
    AnalyticsOrdersResponse,
)
from backend.app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", response_model=AnalyticsOverviewResponse)
def get_analytics_overview(
    period_days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Get comprehensive analytics overview for the caller's merchant."""
    svc = AnalyticsService(db)
    overview = svc.get_overview(ctx.merchant_id, period_days=period_days)
    return overview


@router.get("/revenue", response_model=RevenueTimeSeriesResponse)
def get_revenue_time_series(
    period_days: int = Query(30, ge=1, le=365),
    granularity: str = Query("day", pattern="^(day|week|month)$"),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Get revenue time series for the caller's merchant."""
    data = AnalyticsService(db).get_revenue_series(
        ctx.merchant_id, period_days, granularity
    )

    return {
        "merchant_id": str(ctx.merchant_id),
        "period_days": period_days,
        "data": data,
    }


@router.get("/orders/trend", response_model=OrderTimeSeriesResponse)
def get_orders_time_series(
    period_days: int = Query(30, ge=1, le=365),
    granularity: str = Query("day", pattern="^(day|week|month)$"),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Get orders time series for the caller's merchant."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import func

    from backend.app.models.order import Order
    from backend.app.models.enums import OrderStatus

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=period_days)

    if granularity == "day":
        date_trunc = func.date(Order.created_at)
    elif granularity == "week":
        date_trunc = func.date_trunc("week", Order.created_at)
    else:
        date_trunc = func.date_trunc("month", Order.created_at)

    rows = db.execute(
        select(date_trunc.label("period"), func.count(Order.id))
        .where(Order.merchant_id == ctx.merchant_id)
        .where(Order.created_at >= start)
        .group_by("period")
        .order_by("period")
    ).all()

    data = [
        {"date": str(row.period), "value": Decimal(str(row[1]))}
        for row in rows
    ]

    return {
        "merchant_id": str(ctx.merchant_id),
        "period_days": period_days,
        "data": data,
    }


@router.get("/customers/trend", response_model=CustomerTimeSeriesResponse)
def get_customers_time_series(
    period_days: int = Query(30, ge=1, le=365),
    granularity: str = Query("day", pattern="^(day|week|month)$"),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Get new customers time series for the caller's merchant."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import func

    from backend.app.models.customer import Customer

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=period_days)

    if granularity == "day":
        date_trunc = func.date(Customer.created_at)
    elif granularity == "week":
        date_trunc = func.date_trunc("week", Customer.created_at)
    else:
        date_trunc = func.date_trunc("month", Customer.created_at)

    rows = db.execute(
        select(date_trunc.label("period"), func.count(Customer.id))
        .where(Customer.merchant_id == ctx.merchant_id)
        .where(Customer.created_at >= start)
        .group_by("period")
        .order_by("period")
    ).all()

    data = [
        {"date": str(row.period), "value": Decimal(str(row[1]))}
        for row in rows
    ]

    return {
        "merchant_id": str(ctx.merchant_id),
        "period_days": period_days,
        "data": data,
    }


@router.get("/transactions", response_model=AnalyticsTransactionsResponse)
def get_transactions(
    period_days: int = Query(30, ge=1, le=365),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    result = AnalyticsService(db).get_transactions(
        ctx.merchant_id, period_days, limit, offset
    )
    return {"merchant_id": str(ctx.merchant_id), "period_days": period_days, **result}


@router.get("/customers", response_model=AnalyticsCustomersResponse)
def get_customers(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    result = AnalyticsService(db).get_customers(ctx.merchant_id, limit, offset)
    return {"merchant_id": str(ctx.merchant_id), **result}


@router.get("/orders", response_model=AnalyticsOrdersResponse)
def get_orders(
    period_days: int = Query(30, ge=1, le=365),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    result = AnalyticsService(db).get_orders(
        ctx.merchant_id, period_days, limit, offset
    )
    return {"merchant_id": str(ctx.merchant_id), "period_days": period_days, **result}