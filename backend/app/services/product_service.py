"""ProductService."""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from backend.app.models.product import Product
from backend.app.repositories.product import ProductRepository
from backend.app.core.logging import get_logger

log = get_logger(__name__)


class ProductService:
    def __init__(self, db: Session) -> None:
        self._repo = ProductRepository(db)

    def list_products(
        self,
        merchant_id: uuid.UUID,
        *,
        active_only: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Product]:
        return self._repo.list_by_merchant(
            merchant_id, active_only=active_only, limit=limit, offset=offset
        )

    def get_product(self, product_id: uuid.UUID) -> Product | None:
        return self._repo.get_by_id(product_id)
