"""
Generic base repository.

Provides common CRUD operations so concrete repositories only need to
implement query methods specific to their domain entity.
"""
from __future__ import annotations

import uuid
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """
    Generic repository with get/list/create/delete helpers.

    Subclasses must set `model` to the SQLAlchemy model class.
    """

    model: type[ModelT]

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # Core helpers
    # ------------------------------------------------------------------ #

    def get_by_id(self, record_id: uuid.UUID) -> ModelT | None:
        return self.db.get(self.model, record_id)

    def exists(self, record_id: uuid.UUID) -> bool:
        return self.get_by_id(record_id) is not None

    def list_all(self, limit: int = 100, offset: int = 0) -> list[ModelT]:
        stmt = select(self.model).limit(limit).offset(offset)
        return list(self.db.scalars(stmt).all())

    def add(self, instance: ModelT) -> ModelT:
        self.db.add(instance)
        self.db.flush()
        return instance

    def delete(self, instance: ModelT) -> None:
        self.db.delete(instance)
        self.db.flush()
