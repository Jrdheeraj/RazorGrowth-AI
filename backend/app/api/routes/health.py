"""Health check route."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    """Liveness probe — returns 200 when the application is running."""
    return {"status": "healthy"}
