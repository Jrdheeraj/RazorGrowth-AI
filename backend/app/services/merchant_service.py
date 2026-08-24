"""MerchantService."""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from backend.app.models.merchant import Merchant
from backend.app.repositories.merchant import MerchantRepository
from backend.app.core.logging import get_logger

log = get_logger(__name__)


class MerchantService:
    def __init__(self, db: Session) -> None:
        self._repo = MerchantRepository(db)

    def list_merchants(self, limit: int = 100, offset: int = 0) -> list[Merchant]:
        return self._repo.list_all(limit=limit, offset=offset)

    def get_merchant(self, merchant_id: uuid.UUID) -> Merchant | None:
        return self._repo.get_by_id(merchant_id)

    def get_merchant_by_slug(self, slug: str) -> Merchant | None:
        return self._repo.get_by_slug(slug)
