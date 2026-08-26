"""
FastAPI security dependencies — Phase 6.

Request flow for every protected endpoint:

    Authorization: Bearer <jwt>
        → decode + validate token          (core.security.decode_access_token)
        → load User                        (must exist, status == active)
        → resolve MerchantContext          (memberships of the user)
        → enforce role requirement         (core.roles matrix)

Tenant isolation rule:
    The merchant identity is derived from the AUTHENTICATED user's active
    memberships. A client-supplied merchant_id is accepted only when it
    matches one of those memberships; otherwise the request is rejected
    with 403 MERCHANT_ACCESS_DENIED (existence never disclosed).

AUTH_MODE:
    "required" (default, production): requests without a valid token are
        rejected with 401.
    "optional" (development convenience ONLY): unauthenticated requests fall
        back to the legacy single-tenant behaviour so existing local tooling
        and tests keep working. Authenticated requests are fully validated
        in BOTH modes — optional mode never weakens validation of real tokens.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Callable

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.roles import (
    can_approve,
    can_manage_users,
    can_run_operations,
)
from backend.app.core.security import TokenExpiredError, decode_access_token
from backend.app.db.session import get_db
from backend.app.models.enums import MembershipStatus, UserRole, UserStatus
from backend.app.models.membership import MerchantMembership
from backend.app.models.user import User


# ─────────────────────────────────────────────────────────────────────────────
# Errors (stable, client-safe codes; no internal details leaked)
# ─────────────────────────────────────────────────────────────────────────────


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=403, detail=detail)


# ─────────────────────────────────────────────────────────────────────────────
# Current-user resolution
# ─────────────────────────────────────────────────────────────────────────────


def _extract_bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization") or ""
    if not header.startswith("Bearer "):
        return None
    token = header[len("Bearer "):].strip()
    return token or None


def _load_and_validate_user(db: Session, claims: dict) -> User:
    """Resolve the JWT subject to an ACTIVE human user."""
    try:
        user_id = uuid.UUID(str(claims.get("sub", "")))
    except ValueError as exc:
        # A syntactically valid token pointing at a non-user principal
        # (e.g. a forged 'agent' identity) must fail closed.
        raise _unauthorized("TOKEN_INVALID") from exc

    user = db.get(User, user_id)
    if user is None:
        raise _unauthorized("TOKEN_INVALID")
    if user.status == UserStatus.disabled:
        raise _forbidden("USER_DISABLED")
    return user


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """
    Mandatory authentication dependency.

    Raises 401 when no valid Bearer token is supplied — regardless of mode.
    """
    token = _extract_bearer_token(request)
    if token is None:
        raise _unauthorized("NOT_AUTHENTICATED")
    try:
        claims = decode_access_token(token)
    except TokenExpiredError as exc:
        raise _unauthorized("TOKEN_EXPIRED") from exc
    except Exception as exc:  # invalid signature, malformed, wrong type…
        raise _unauthorized("TOKEN_INVALID") from exc
    return _load_and_validate_user(db, claims)


def get_current_user_optional(
    request: Request,
    db: Session = Depends(get_db),
) -> User | None:
    """
    Mode-aware authentication dependency.

      AUTH_MODE=required → identical to get_current_user.
      AUTH_MODE=optional → returns None when no Authorization header is
          present (legacy fallback); still validates any token presented.
    """
    if _extract_bearer_token(request) is None:
        settings = get_settings()
        if settings.AUTH_MODE == "required":
            raise _unauthorized("NOT_AUTHENTICATED")
        return None
    return get_current_user(request=request, db=db)


# ─────────────────────────────────────────────────────────────────────────────
# Merchant security context
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MerchantContext:
    """Resolved tenant + actor identity for one request."""

    merchant_id: uuid.UUID
    user: User | None                 # None ONLY in optional-anonymous mode
    membership: MerchantMembership | None
    authenticated: bool
    # True when the tenant was pinned by authentication or an explicit
    # client-supplied merchant id. False only for anonymous optional-mode
    # callers who did NOT name a merchant (legacy "serve everything" path).
    explicit_merchant: bool = True

    @property
    def role(self) -> str | None:
        return self.membership.role.value if self.membership else None


def _active_memberships(db: Session, user: User) -> list[MerchantMembership]:
    rows = (
        db.query(MerchantMembership)
        .filter(
            MerchantMembership.user_id == user.id,
            MerchantMembership.status == MembershipStatus.active,
        )
        .all()
    )
    return list(rows)


def _resolve_tenant(
    db: Session,
    user: User,
    claimed_merchant_id: uuid.UUID | None,
) -> MerchantContext:
    """Derive the tenant strictly from the user's active memberships."""
    memberships = _active_memberships(db, user)

    if claimed_merchant_id is not None:
        for m in memberships:
            if m.merchant_id == claimed_merchant_id:
                return MerchantContext(claimed_merchant_id, user, m, True)
        # Authenticated but not a member of the requested merchant — deny
        # without disclosing whether that merchant exists at all.
        raise _forbidden("MERCHANT_ACCESS_DENIED")

    if len(memberships) == 1:
        m = memberships[0]
        return MerchantContext(m.merchant_id, user, m, True)

    if not memberships:
        raise _forbidden("NO_MERCHANT_MEMBERSHIP")

    # Multiple merchants and no explicit selection → force explicit choice.
    raise HTTPException(status_code=400, detail="AMBIGUOUS_MERCHANT")


def _legacy_anonymous_context(
    db: Session,
    claimed_merchant_id: uuid.UUID | None,
) -> MerchantContext:
    """
    Optional-mode anonymous fallback preserving pre-auth behaviour:
    use the supplied merchant_id (validated to exist), else the first
    merchant in the DB.
    """
    if claimed_merchant_id is not None:
        from backend.app.models.merchant import Merchant

        if db.get(Merchant, claimed_merchant_id) is None:
            raise HTTPException(status_code=404, detail="MERCHANT_NOT_FOUND")
        return MerchantContext(
            claimed_merchant_id, None, None, False, explicit_merchant=True
        )
    from backend.app.repositories.merchant import MerchantRepository

    merchants = MerchantRepository(db).list_all(limit=1)
    if not merchants:
        raise HTTPException(status_code=404, detail="MERCHANT_NOT_FOUND")
    return MerchantContext(
        merchants[0].id, None, None, False, explicit_merchant=False
    )


def _merchant_context_dependency(
    request: Request,
    db: Session,
    claimed_merchant_id: uuid.UUID | None,
) -> MerchantContext:
    user = get_current_user_optional(request=request, db=db)
    if user is None:
        return _legacy_anonymous_context(db, claimed_merchant_id)
    return _resolve_tenant(db, user, claimed_merchant_id)


# ── concrete FastAPI dependencies ───────────────────────────────────────────


def merchant_ctx(
    request: Request,
    db: Session = Depends(get_db),
    merchant_id: uuid.UUID | None = Query(default=None),
) -> MerchantContext:
    """
    Read-context dependency: analyst or above may read.

    The resolved tenant always comes from authentication; a client-supplied
    merchant_id is validated against active memberships.
    """
    return _merchant_context_dependency(request, db, merchant_id)


def _role_guarded_ctx(role_check: Callable[[UserRole], bool]):
    """
    Factory for write/operational dependencies.

    Role enforcement applies only to authenticated callers; anonymous
    optional-mode traffic keeps legacy behaviour (development convenience).
    Production runs AUTH_MODE=required where every caller is authenticated
    and therefore always role-checked.
    """

    def _dep(
        request: Request,
        db: Session = Depends(get_db),
        merchant_id: uuid.UUID | None = Query(default=None),
    ) -> MerchantContext:
        ctx = _merchant_context_dependency(request, db, merchant_id)
        if ctx.authenticated and ctx.membership is not None:
            if not role_check(ctx.membership.role):
                raise _forbidden("INSUFFICIENT_ROLE")
        elif ctx.authenticated:
            raise _forbidden("NO_MERCHANT_MEMBERSHIP")
        return ctx

    return _dep


operator_ctx = _role_guarded_ctx(can_run_operations)
approver_ctx = _role_guarded_ctx(can_approve)


# ── helper for body-supplied merchant ids ───────────────────────────────────


def resolve_claimed_merchant(
    ctx: MerchantContext,
    claimed: uuid.UUID | None,
) -> uuid.UUID:
    """
    Validate a merchant_id that arrived inside a request BODY.

    Must equal the authenticated context's merchant (filled from it when
    omitted). Anonymous optional-mode callers keep legacy behaviour.
    """
    if not ctx.authenticated:
        return claimed if claimed is not None else ctx.merchant_id
    if claimed is None:
        return ctx.merchant_id
    if claimed != ctx.merchant_id:
        raise _forbidden("MERCHANT_ACCESS_DENIED")
    return claimed


__all__ = [
    "MerchantContext",
    "get_current_user",
    "get_current_user_optional",
    "merchant_ctx",
    "operator_ctx",
    "approver_ctx",
    "resolve_claimed_merchant",
]
