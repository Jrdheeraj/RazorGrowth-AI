"""lease fencing generation and reconciliation status

Phase 2 recovery-safety hardening.

What this adds
--------------
``agent_workflow_runs.lease_generation``
    A monotonically increasing fencing token, incremented by every successful
    ownership claim and by the stale-workflow sweep.

    A lease alone cannot stop a paused worker. It can be descheduled past its
    lease expiry, another worker legitimately takes the cycle over, and then the
    first worker wakes up and writes -- overwriting the newer owner's state or
    marking its steps complete. The generation is carried by every protected
    write and compared against the stored value inside the same transaction, so
    an obsolete worker is rejected rather than trusted.

    Generation 0 is the sentinel for "never claimed": a worker that never
    claimed ownership can therefore never satisfy the check.

``agent_workflow_runs.status`` widened to VARCHAR(24)
    ``needs_reconciliation`` is 20 characters, which is exactly the old
    VARCHAR(20) boundary and leaves no margin. Widened for the same reason
    ``agent_runs.status`` already was.

``agent_runs.status`` unchanged in width
    ``needs_reconciliation`` (20) already fits the existing VARCHAR(24).

Migration safety
----------------
* Every operation is guarded, so re-running is a no-op.
* ``lease_generation`` is added with a server default of 0 and is NOT NULL:
  historical rows default to the "never claimed" sentinel, which can never pass
  a fencing check. That is the safe direction -- an old row is refused, never
  trusted.
* No historical row is deleted or rewritten.

Revision ID: e5a1b3c7d904
Revises: d4e7f1a9c205
Create Date: 2026-10-17

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e5a1b3c7d904"
down_revision = "d4e7f1a9c205"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if "lease_generation" not in _columns("agent_workflow_runs"):
        op.add_column(
            "agent_workflow_runs",
            sa.Column(
                "lease_generation",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )

    # Widen the cycle status so needs_reconciliation (20 chars) has margin.
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column(
            "agent_workflow_runs",
            "status",
            type_=sa.String(length=24),
            existing_type=sa.String(length=20),
            existing_nullable=False,
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        # Narrow first: a row already holding needs_reconciliation would not
        # fit, so refuse rather than truncate silently.
        op.execute(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM agent_workflow_runs "
            "WHERE status = 'needs_reconciliation') THEN "
            "RAISE EXCEPTION 'cannot narrow status: needs_reconciliation rows exist'; "
            "END IF; END $$;"
        )
        op.alter_column(
            "agent_workflow_runs",
            "status",
            type_=sa.String(length=20),
            existing_type=sa.String(length=24),
            existing_nullable=False,
        )
    if "lease_generation" in _columns("agent_workflow_runs"):
        op.drop_column("agent_workflow_runs", "lease_generation")
