"""ProductRepository."""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select

from backend.app.models.product import Product
from backend.app.repositories.base import BaseRepository


class ProductRepository(BaseRepository[Product]):
    model = Product

    def list_by_merchant(
        self,
        merchant_id: uuid.UUID,
        *,
        active_only: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Product]:
        stmt = (
            select(Product)
            .where(Product.merchant_id == merchant_id)
            .order_by(Product.name)
            .limit(limit)
            .offset(offset)
        )
        if active_only:
            stmt = stmt.where(Product.active.is_(True))
        return list(self.db.scalars(stmt).all())

    def get_by_sku(self, merchant_id: uuid.UUID, sku: str) -> Product | None:
        stmt = select(Product).where(
            Product.merchant_id == merchant_id,
            Product.sku == sku,
        )
        return self.db.scalars(stmt).first()

    def list_by_category(
        self, merchant_id: uuid.UUID, category: str
    ) -> list[Product]:
        stmt = (
            select(Product)
            .where(
                Product.merchant_id == merchant_id,
                Product.category == category,
                Product.active.is_(True),
            )
            .order_by(Product.price)
        )
        return list(self.db.scalars(stmt).all())

    def create(
        self,
        *,
        merchant_id: uuid.UUID,
        name: str,
        category: str,
        price: Decimal,
        sku: str | None = None,
        description: str | None = None,
        stock_quantity: int = 0,
    ) -> Product:
        product = Product(
            merchant_id=merchant_id,
            name=name,
            category=category,
            price=price,
            sku=sku,
            description=description,
            stock_quantity=stock_quantity,
        )
        return self.add(product)
