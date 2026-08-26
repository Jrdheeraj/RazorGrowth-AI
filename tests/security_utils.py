"""
Shared helpers for the Phase 6 security test suite.

These utilities create fully-authenticated worlds (merchants + users +
memberships) and mint real tokens through the public API surface.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from backend.app.core.security import create_access_token, hash_password
from backend.app.models.enums import (
    Currency,
    MembershipStatus,
    MerchantStatus,
    UserRole,
    UserStatus,
)
from backend.app.models.membership import MerchantMembership
from backend.app.models.merchant import Merchant
from backend.app.models.user import User

TEST_SECRET = "test-only-secret-key-do-not-use-in-production"


def make_merchant(db: Session, slug_hint: str = "m") -> Merchant:
    slug = f"{slug_hint}-{uuid.uuid4().hex[:10]}"
    m = Merchant(
        name=f"Merchant {slug}",
        slug=slug,
        email=f"owner@{slug}.test",
        status=MerchantStatus.active,
        currency=Currency.INR,
    )
    db.add(m)
    db.commit()
    return m


def make_user(db: Session, email_hint: str = "user") -> User:
    email = f"{email_hint}-{uuid.uuid4().hex[:10]}@security.test"
    u = User(
        email=email,
        password_hash=hash_password("CorrectHorse12"),
        full_name="Security Test User",
        status=UserStatus.active,
    )
    db.add(u)
    db.commit()
    return u


def make_membership(
    db: Session,
    user: User,
    merchant: Merchant,
    role: UserRole = UserRole.owner,
) -> MerchantMembership:
    mem = MerchantMembership(
        user_id=user.id,
        merchant_id=merchant.id,
        role=role,
        status=MembershipStatus.active,
    )
    db.add(mem)
    db.commit()
    return mem


def make_world(
    db: Session,
    role: UserRole = UserRole.owner,
    slug_hint: str = "w",
) -> tuple[Merchant, User, MerchantMembership]:
    """Convenience: one merchant + one user + one membership."""
    m = make_merchant(db, slug_hint)
    u = make_user(db, slug_hint)
    mem = make_membership(db, u, m, role)
    return m, u, mem


def bearer(u: User) -> dict[str, str]:
    """Authorization headers carrying a freshly-minted valid token."""
    token, _ = create_access_token(u.id, u.email)
    return {"Authorization": f"Bearer {token}"}


def register_and_login(
    client: Any, email: str | None = None, password: str = "CorrectHorse12"
) -> dict[str, Any]:
    """Full API round-trip: register a user, then login for a token."""
    email = email or f"api-{uuid.uuid4().hex[:10]}@security.test"
    r = client.post(
        "/api/auth/register", json={"email": email, "password": password}
    )
    assert r.status_code == 201, r.text
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()
