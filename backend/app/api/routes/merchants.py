"""Merchant routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user_optional
from backend.app.db.session import get_db
from backend.app.models.enums import MembershipStatus
from backend.app.models.membership import MerchantMembership
from backend.app.schemas.merchant import MerchantResponse
from backend.app.services.merchant_service import MerchantService

router = APIRouter(prefix="/merchants", tags=["merchants"])


@router.get("", response_model=list[MerchantResponse])
def list_merchants(
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_optional),
) -> list[MerchantResponse]:
    """
    List merchants visible to the caller.

    Authenticated users see ONLY merchants they hold an active membership
    with (tenant isolation). Anonymous optional-mode callers keep legacy
    behaviour (all merchants) for local development convenience.
    """
    svc = MerchantService(db)
    if user is None:
        return svc.list_merchants(limit=limit, offset=offset)

    rows = (
        db.query(MerchantMembership)
        .filter(
            MerchantMembership.user_id == user.id,
            MerchantMembership.status == MembershipStatus.active,
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    merchants = [row.merchant for row in rows]
    return [
        MerchantResponse.model_validate(m, from_attributes=True) for m in merchants
    ]
