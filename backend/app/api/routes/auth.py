"""
Authentication & membership API — Phase 6.

Endpoints (final paths after the /api application prefix):
  POST   /api/auth/register                          — self-registration (toggleable)
  POST   /api/auth/login                             — credential exchange → JWT
  GET    /api/auth/me                                — current user + memberships
  GET    /api/auth/merchants                         — merchants the caller can access
  GET    /api/auth/merchants/{merchant_id}/members   — list members   (admin/owner)
  POST   /api/auth/merchants/{merchant_id}/members   — attach member  (admin/owner)
  PATCH  /api/auth/merchants/{merchant_id}/members/{user_id} — role/status
  DELETE /api/auth/merchants/{merchant_id}/members/{user_id} — remove member

Security notes:
  - Login failures always return 401 INVALID_CREDENTIALS regardless of
    whether the email exists (no account enumeration).
  - Passwords are validated against the policy, hashed with scrypt, and
    NEVER included in responses or logs.
  - Membership mutations enforce the owner/admin rules from core.roles.
"""
from __future__ import annotations

import logging
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.deps import _forbidden, get_current_user
from backend.app.core.config import get_settings
from backend.app.core.ratelimit import enforce_auth_rate_limit
from backend.app.core.roles import can_manage_owners, can_manage_users
from backend.app.core.security import (
    PasswordPolicyError,
    hash_password,
    validate_password_policy,
)
from backend.app.db.session import get_db
from backend.app.models.enums import Currency, MembershipStatus, MerchantStatus, UserRole, UserStatus
from backend.app.models.membership import MerchantMembership
from backend.app.models.merchant import Merchant
from backend.app.models.user import User
from backend.app.schemas.auth import (
    AccessibleMerchantsResponse,
    CreateMembershipRequest,
    LoginRequest,
    MeResponse,
    MembershipOut,
    MerchantSummary,
    RegisterRequest,
    TokenResponse,
    UpdateMembershipRequest,
    UserOut,
)
from backend.app.core.security import create_access_token, verify_password

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

GENERIC_CREDENTIALS_ERROR = HTTPException(
    status_code=401, detail="INVALID_CREDENTIALS",
    headers={"WWW-Authenticate": "Bearer"},
)


def _membership_out(m: MerchantMembership) -> dict:
    return {
        "id": str(m.id),
        "merchant_id": str(m.merchant_id),
        "role": m.role.value if isinstance(m.role, UserRole) else str(m.role),
        "status": m.status.value if isinstance(m.status, MembershipStatus) else str(m.status),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Registration & login
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/register", response_model=UserOut, status_code=201)
def register(
    request: Request,
    payload: RegisterRequest,
    db: Session = Depends(get_db),
    _rl: None = Depends(enforce_auth_rate_limit),
) -> dict:
    """Create a new human user. Disabled via AUTH_ENABLE_REGISTRATION=false."""
    settings = get_settings()
    if not settings.AUTH_ENABLE_REGISTRATION:
        raise HTTPException(status_code=403, detail="REGISTRATION_DISABLED")

    existing = db.execute(
        select(User).where(User.email == payload.email)
    ).scalar_one_or_none()
    if existing is not None:
        # Same generic response as success-path validation would allow;
        # do not reveal more than necessary.
        raise HTTPException(status_code=409, detail="EMAIL_ALREADY_REGISTERED")

    try:
        validate_password_policy(payload.password)
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    user = User(
        id=uuid.uuid4(),
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        status=UserStatus.active,
    )
    db.add(user)
    db.flush()  # assign user.id before creating the workspace

    # Multi-tenant signup: every new user gets their OWN workspace with an
    # independent default catalog (idempotent bootstrap in backend.app.data.seed).
    # No user is ever attached to an existing merchant's data here.
    from backend.app.data.seed import initialize_user_workspace

    merchant = initialize_user_workspace(db, user)

    db.commit()
    log.info("User registered. user=%s merchant=%s", str(user.id), str(merchant.id))
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "status": str(getattr(user.status, "value", user.status)),
    }


@router.post("/login", response_model=TokenResponse)
def login(
    request: Request,
    payload: LoginRequest,
    db: Session = Depends(get_db),
    _rl: None = Depends(enforce_auth_rate_limit),
) -> dict:
    """
    Exchange credentials for an access token.

    Identical error surface for unknown email and wrong password.
    Disabled accounts are refused separately (403 USER_DISABLED).
    """
    user = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        log.info("Failed login attempt (email not logged)")
        raise GENERIC_CREDENTIALS_ERROR
    if user.status == UserStatus.disabled:
        raise _forbidden("USER_DISABLED")

    # Login only verifies credentials and mints a token. Workspace access
    # comes strictly from the user's existing memberships — a user without
    # one gets NO_MERCHANT_MEMBERSHIP on protected endpoints; login never
    # silently attaches anyone to any merchant.

    token, expires_in = create_access_token(user.id, user.email)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": {
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "status": str(getattr(user.status, "value", user.status)),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Current-user introspection
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/me", response_model=MeResponse)
def me(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    rows = (
        db.execute(
            select(MerchantMembership).where(MerchantMembership.user_id == user.id)
        )
        .scalars()
        .all()
    )
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "status": str(getattr(user.status, "value", user.status)),
        "memberships": [_membership_out(m) for m in rows],
    }


@router.get("/merchants", response_model=AccessibleMerchantsResponse)
def accessible_merchants(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    rows = (
        db.execute(
            select(MerchantMembership, Merchant)
            .join(Merchant, Merchant.id == MerchantMembership.merchant_id)
            .where(MerchantMembership.user_id == user.id)
        )
        .all()
    )
    merchants = [
        {
            "id": str(merchant.id),
            "name": merchant.name,
            "slug": merchant.slug,
            "role": membership.role.value if isinstance(membership.role, UserRole)
            else str(membership.role),
        }
        for membership, merchant in rows
    ]
    return {"merchants": merchants}


# ─────────────────────────────────────────────────────────────────────────────
# Membership administration (owner/admin only)
# ─────────────────────────────────────────────────────────────────────────────


def _require_admin_membership(
    db: Session, user: User, merchant_id: uuid.UUID
) -> MerchantMembership:
    row = db.execute(
        select(MerchantMembership).where(
            MerchantMembership.user_id == user.id,
            MerchantMembership.merchant_id == merchant_id,
        )
    ).scalar_one_or_none()
    if row is None or not row.is_active or not can_manage_users(row.role):
        raise _forbidden("MERCHANT_ACCESS_DENIED" if row is None else "INSUFFICIENT_ROLE")
    return row


@router.get("/merchants/{merchant_id}/members")
def list_members(
    merchant_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _require_admin_membership(db, user, merchant_id)
    rows = (
        db.execute(
            select(MerchantMembership, User)
            .join(User, User.id == MerchantMembership.user_id)
            .where(MerchantMembership.merchant_id == merchant_id)
            .order_by(MerchantMembership.created_at.asc())
        )
        .all()
    )
    members = []
    for membership, member in rows:
        out = _membership_out(membership)
        out.update({
            "user_id": str(member.id),
            "email": member.email,
            "full_name": member.full_name,
            "user_status": member.status.value,
        })
        members.append(out)
    return {"merchant_id": str(merchant_id), "members": members}


@router.post("/merchants/{merchant_id}/members", status_code=201)
def add_member(
    merchant_id: uuid.UUID,
    payload: CreateMembershipRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    caller = _require_admin_membership(db, user, merchant_id)
    new_role = UserRole(payload.role)

    # Owner-tier operations require the caller to be an owner.
    if new_role == UserRole.owner and not can_manage_owners(caller.role):
        raise _forbidden("OWNER_REQUIRED")
    if db.get(Merchant, merchant_id) is None:
        raise HTTPException(status_code=404, detail="MERCHANT_NOT_FOUND")

    target = db.execute(
        select(User).where(User.email == payload.email)
    ).scalar_one_or_none()

    temp_password_generated = False
    if target is None:
        if not payload.initial_password:
            raise HTTPException(
                status_code=422,
                detail="INITIAL_PASSWORD_REQUIRED: user does not exist yet; "
                "provide initial_password",
            )
        try:
            validate_password_policy(payload.initial_password)
        except PasswordPolicyError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        target = User(
            id=uuid.uuid4(),
            email=payload.email,
            password_hash=hash_password(payload.initial_password),
            status=UserStatus.active,
        )
        db.add(target)
        db.flush()
        temp_password_generated = bool(payload.initial_password)

    duplicate = db.execute(
        select(MerchantMembership).where(
            MerchantMembership.user_id == target.id,
            MerchantMembership.merchant_id == merchant_id,
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="MEMBERSHIP_EXISTS")

    membership = MerchantMembership(
        id=uuid.uuid4(),
        user_id=target.id,
        merchant_id=merchant_id,
        role=new_role,
        status=MembershipStatus.active,
    )
    db.add(membership)
    db.commit()
    log.info(
        "Membership added. actor=%s merchant=%s user=%s role=%s",
        str(user.id), str(merchant_id), str(target.id), new_role.value,
    )
    out = _membership_out(membership)
    out.update({
        "user_id": str(target.id),
        "email": target.email,
        "temporary_password_set": temp_password_generated,
    })
    return out


@router.patch("/merchants/{merchant_id}/members/{user_id}")
def update_member(
    merchant_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: UpdateMembershipRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    caller = _require_admin_membership(db, user, merchant_id)
    membership = db.execute(
        select(MerchantMembership).where(
            MerchantMembership.user_id == user_id,
            MerchantMembership.merchant_id == merchant_id,
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=404, detail="MEMBERSHIP_NOT_FOUND")

    touches_owner_tier = (
        membership.role == UserRole.owner
        or (payload.role is not None and payload.role == "owner")
    )
    if touches_owner_tier and not can_manage_owners(caller.role):
        raise _forbidden("OWNER_REQUIRED")

    loses_ownership = touches_owner_tier and (
        payload.role is not None
        and membership.status == MembershipStatus.active
        and (
            payload.role != "owner"
            or (payload.status is not None and payload.status == "disabled")
        )
    )
    becomes_disabled = payload.status is not None and payload.status == "disabled"
    if (loses_ownership or (becomes_disabled and membership.role == UserRole.owner)):
        _prevent_last_owner_lockout(db, merchant_id, membership)

    if payload.role is not None:
        membership.role = UserRole(payload.role)
    if payload.status is not None:
        membership.status = MembershipStatus(payload.status)

    db.commit()
    out = _membership_out(membership)
    out["user_id"] = str(user_id)
    return out


@router.delete("/merchants/{merchant_id}/members/{user_id}", status_code=200)
def remove_member(
    merchant_id: uuid.UUID,
    user_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    caller = _require_admin_membership(db, user, merchant_id)
    membership = db.execute(
        select(MerchantMembership).where(
            MerchantMembership.user_id == user_id,
            MerchantMembership.merchant_id == merchant_id,
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=404, detail="MEMBERSHIP_NOT_FOUND")

    if membership.role == UserRole.owner and not can_manage_owners(caller.role):
        raise _forbidden("OWNER_REQUIRED")
    if membership.role == UserRole.owner:
        owners = db.execute(
            select(MerchantMembership).where(
                MerchantMembership.merchant_id == merchant_id,
                MerchantMembership.role == UserRole.owner,
                MerchantMembership.status == MembershipStatus.active,
            )
        ).scalars().all()
        if len(list(owners)) <= 1:
            raise _forbidden("LAST_OWNER_PROTECTED")

    db.delete(membership)
    db.commit()
    log.info(
        "Membership removed. actor=%s merchant=%s user=%s",
        str(user.id), str(merchant_id), str(user_id),
    )
    return {"removed": True, "merchant_id": str(merchant_id), "user_id": str(user_id)}


def _prevent_last_owner_lockout(
    db: Session, merchant_id: uuid.UUID, changing: MerchantMembership
) -> None:
    if changing.role != UserRole.owner:
        return
    others = [
        m for m in db.execute(
            select(MerchantMembership).where(
                MerchantMembership.merchant_id == merchant_id,
                MerchantMembership.role == UserRole.owner,
                MerchantMembership.status == MembershipStatus.active,
            )
        ).scalars().all()
        if m.id != changing.id
    ]
    if not others:
        raise _forbidden("LAST_OWNER_PROTECTED")
