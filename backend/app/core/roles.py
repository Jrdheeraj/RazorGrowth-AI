"""
Role-based permission matrix — Phase 6.

Roles are attached to merchant MEMBERSHIPS (user ↔ merchant ↔ role), so all
permissions below are implicitly tenant-scoped: a role at merchant A confers
nothing at merchant B.

Matrix (columns are role tiers, ordered strongest → weakest):

  Capability                          owner  admin  operator  analyst
  ────────────────────────────────────────────────────────────────────────
  read merchant-scoped data             ✔      ✔       ✔        ✔
  run agents / simulations / analysis   ✔      ✔       ✔        ✘ (read-only)
  execute approved actions              ✔      ✔       ✔        ✘
  approve / reject actions              ✔      ✔       ✘        ✘
  manage users & memberships            ✔      ✔*      ✘        ✘
  transfer / revoke ownership           ✔      ✘       ✘        ✘

  * admins may manage operator/analyst memberships only; any operation that
    creates, elevates to, or removes an `owner` requires `owner`.

Invariants:
  - NO role bypasses guardrails. Approval and execution remain behind the
    guardrail chain regardless of who is authenticated.
  - Agents are NOT users and hold NO role.
"""
from __future__ import annotations

from backend.app.models.enums import UserRole

# Ordered strength — index comparisons drive hierarchical checks.
ROLE_STRENGTH: dict[UserRole, int] = {
    UserRole.owner: 3,
    UserRole.admin: 2,
    UserRole.operator: 1,
    UserRole.analyst: 0,
}


class RolePermissionError(PermissionError):
    """Raised when the caller's role does not permit the operation."""


def _roles_at_least(membership_role: UserRole, minimum: UserRole) -> bool:
    return ROLE_STRENGTH[membership_role] >= ROLE_STRENGTH[minimum]


def can_read(membership_role: UserRole) -> bool:
    """All roles may read merchant-scoped data."""
    return True


def can_run_operations(membership_role: UserRole) -> bool:
    """Agent runs, analyses, simulations, ingest, refreshes, execution."""
    return _roles_at_least(membership_role, UserRole.operator)


def can_approve(membership_role: UserRole) -> bool:
    """Human approval / rejection of proposed actions."""
    return _roles_at_least(membership_role, UserRole.admin)


def can_manage_users(membership_role: UserRole) -> bool:
    """Create/list/modify/disable memberships (subject to owner rules)."""
    return _roles_at_least(membership_role, UserRole.admin)


def can_manage_owners(membership_role: UserRole) -> bool:
    """Grant/revoke/change the owner role itself."""
    return membership_role == UserRole.owner


def assert_can(target_role_for: str, checker, role: UserRole) -> None:
    """Raise RolePermissionError with a stable client-safe code."""
    if not checker(role):
        raise RolePermissionError(
            f"INSUFFICIENT_ROLE: role '{role.value}' may not {target_role_for}"
        )
