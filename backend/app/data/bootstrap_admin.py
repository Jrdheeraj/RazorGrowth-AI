"""
Bootstrap the first human owner for a merchant.

Usage (from the project root):

    python -m backend.app.data.bootstrap_admin \
        --email owner@example.com --password 'A-Long-Password-123'

    # attach to a specific merchant instead of the first one:
    python -m backend.app.data.bootstrap_admin \
        --email owner@example.com --password 'A-Long-Password-123' \
        --merchant-slug my-merchant

Idempotent: re-running with the same email/merchant is safe.
The password is validated against the policy and stored only as an
scrypt hash. It is never printed or logged.

Requires AUTH_SECRET_KEY to be set in the environment when minting tokens
is desired; this tool only creates accounts and memberships.
"""
from __future__ import annotations

import argparse
import sys
import uuid

from sqlalchemy import select

from backend.app.core.config import get_settings
from backend.app.core.logging import configure_logging
from backend.app.core.security import PasswordPolicyError, hash_password, validate_password_policy
from backend.app.db.engine import build_engine
from backend.app.db.session import init_db
from backend.app.models.enums import MembershipStatus, UserRole, UserStatus
from backend.app.models.membership import MerchantMembership
from backend.app.models.merchant import Merchant
from backend.app.models.user import User


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a user and attach them as merchant owner."
    )
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--merchant-slug", default=None,
                        help="Attach to this merchant (default: first merchant)")
    parser.add_argument("--role", default="owner",
                        choices=[r.value for r in UserRole])
    args = parser.parse_args()

    settings = get_settings()
    configure_logging("INFO")

    engine = build_engine(settings.DATABASE_URL, echo=False)
    init_db(engine)
    from backend.app.db.session import get_session_factory

    factory = get_session_factory()

    try:
        validate_password_policy(args.password)
    except PasswordPolicyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    db = factory()
    try:
        if args.merchant_slug:
            merchant = db.execute(
                select(Merchant).where(Merchant.slug == args.merchant_slug)
            ).scalar_one_or_none()
            if merchant is None:
                print(f"error: no merchant with slug {args.merchant_slug!r}",
                      file=sys.stderr)
                return 1
        else:
            merchant = db.query(Merchant).order_by(Merchant.created_at.asc()).first()
            if merchant is None:
                print("error: no merchants exist. Run "
                      "`python -m backend.app.data.seed` first.", file=sys.stderr)
                return 1

        user = db.execute(
            select(User).where(User.email == args.email.lower().strip())
        ).scalar_one_or_none()
        created_user = False
        if user is None:
            user = User(
                id=uuid.uuid4(),
                email=args.email.lower().strip(),
                password_hash=hash_password(args.password),
                status=UserStatus.active,
            )
            db.add(user)
            db.flush()
            created_user = True

        membership = db.execute(
            select(MerchantMembership).where(
                MerchantMembership.user_id == user.id,
                MerchantMembership.merchant_id == merchant.id,
            )
        ).scalar_one_or_none()
        created_membership = False
        if membership is None:
            membership = MerchantMembership(
                id=uuid.uuid4(),
                user_id=user.id,
                merchant_id=merchant.id,
                role=UserRole(args.role),
                status=MembershipStatus.active,
            )
            db.add(membership)
            created_membership = True

        db.commit()
        print(f"merchant : {merchant.name} ({merchant.id})")
        print(f"user     : {user.email} ({user.id})"
              f" {'created' if created_user else 'existing'}")
        print(f"membership: role={membership.role.value} "
              f"{'created' if created_membership else 'existing'}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
