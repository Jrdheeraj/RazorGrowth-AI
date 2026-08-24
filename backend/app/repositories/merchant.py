"""MerchantRepository."""
from __future__ import annotations

import uuid

from sqlalchemy import select

from backend.app.models.merchant import Merchant
from backend.app.repositories.base import BaseRepository


class MerchantRepository(BaseRepository[Merchant]):
    model = Merchant

    def get_by_slug(self, slug: str) -> Merchant | None:
        stmt = select(Merchant).where(Merchant.slug == slug)
        return self.db.scalars(stmt).first()

    def get_by_email(self, email: str) -> Merchant | None:
        stmt = select(Merchant).where(Merchant.email == email)
        return self.db.scalars(stmt).first()

    def create(
        self,
        *,
        name: str,
        slug: str,
        email: str,
        currency: str = "INR",
    ) -> Merchant:
        merchant = Merchant(
            name=name,
            slug=slug,
            email=email,
            currency=currency,
        )
        return self.add(merchant)
