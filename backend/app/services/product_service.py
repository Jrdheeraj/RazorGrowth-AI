"""ProductService."""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.app.models.product import Product
from backend.app.repositories.product import ProductRepository
from backend.app.core.logging import get_logger

log = get_logger(__name__)


class ProductService:
    def __init__(self, db: Session) -> None:
        self._repo = ProductRepository(db)
        self._db = db

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

    def get_product_by_merchant(self, merchant_id: uuid.UUID, product_id: uuid.UUID) -> Product | None:
        product = self._repo.get_by_id(product_id)
        if product and product.merchant_id == merchant_id:
            return product
        return None

    def create_product(
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
        if sku:
            existing = self._repo.get_by_sku(merchant_id, sku)
            if existing:
                raise ValueError(f"Product with SKU {sku} already exists for this merchant")

        product = self._repo.create(
            merchant_id=merchant_id,
            name=name,
            category=category,
            price=price,
            sku=sku,
            description=description,
            stock_quantity=stock_quantity,
        )
        self._db.flush()
        log.info("Product created. id=%s merchant=%s sku=%s", str(product.id), merchant_id, sku)
        return product

    def update_product(
        self,
        product_id: uuid.UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        category: str | None = None,
        price: Decimal | None = None,
        sku: str | None = None,
        stock_quantity: int | None = None,
        active: bool | None = None,
    ) -> Product | None:
        product = self._repo.get_by_id(product_id)
        if not product:
            return None

        if sku is not None and sku != product.sku:
            existing = self._repo.get_by_sku(product.merchant_id, sku)
            if existing:
                raise ValueError(f"Product with SKU {sku} already exists for this merchant")
            product.sku = sku

        if name is not None:
            product.name = name
        if description is not None:
            product.description = description
        if category is not None:
            product.category = category
        if price is not None:
            product.price = price
        if stock_quantity is not None:
            product.stock_quantity = stock_quantity
        if active is not None:
            product.active = active

        self._db.flush()
        log.info("Product updated. id=%s", str(product_id))
        return product

    def delete_product(self, product_id: uuid.UUID) -> bool:
        product = self._repo.get_by_id(product_id)
        if not product:
            return False

        # Check if product has order items
        if product.order_items:
            raise ValueError("Cannot delete product with existing order items")

        self._repo.delete(product)
        self._db.flush()
        log.info("Product deleted. id=%s", str(product_id))
        return True
