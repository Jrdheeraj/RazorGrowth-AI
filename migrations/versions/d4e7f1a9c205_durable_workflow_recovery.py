"""durable workflow cycles, step identity and action idempotency

Crash-recovery support for GrowthAgentOrchestrator.

Why
---
``agent_runs`` recorded that an agent ran, but nothing recorded that a
multi-agent CYCLE was in flight. A crashed orchestrator therefore left
per-agent rows with no cycle-level truth: no "this cycle was half-finished",
no way to tell which steps were done, and nothing stopping a later invocation
from replaying the whole plan under the same run id.

This migration adds:

* ``agent_workflow_runs`` -- one durable, resumable cycle per
  (merchant, run_id), carrying the materialised plan, a plan fingerprint, and
  a single-writer lease (owner + expiry + heartbeat).
* ``agent_runs.workflow_id / step_key / step_index / attempt / heartbeat_at``
  -- step-level identity and liveness.

Why the constraint is on (workflow_id, step_key, attempt) and NOT on
(orchestrator_run_id, agent_name)
-------------------------------------------------------------
Agents legitimately repeat inside one plan: ``GROWTH_TEAM_PLAN`` runs
MarketingAgent three times (investigate / cross_examine / rebut) and
GrowthMemoryAgent twice. A per-agent unique constraint would reject valid
workflows. ``step_key`` is derived from the plan POSITION (mode + index +
agent + phase), so every legitimate occurrence has its own key, while a replay
of the same logical step collides. ``attempt`` keeps replans and retries as
history instead of overwriting the first try.

Both new columns on ``agent_runs`` are nullable, so historical rows need no
backfill and do not collide (NULLs are distinct in PostgreSQL and SQLite).

Idempotency on actions
----------------------
``agent_actions.idempotency_key`` + ``uq_agent_actions_merchant_idempotency``
makes a repeated logical proposal resolve to the existing row. Enforced by the
database so two concurrent retries cannot both win a read-then-write race.
NULL keys (every historical row) do not collide, so this is additive.

No historical row is deleted or rewritten.

Revision ID: d4e7f1a9c205
Revises: p5e2r0na1z04
Create Date: 2026-10-17

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "d4e7f1a9c205"
down_revision = "p5e2r0na1z04"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _columns(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def _add_column(table: str, col: sa.Column) -> None:
    if col.name not in _columns(table):
        op.add_column(table, col)


def _has_constraint(table: str, name: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    names = {c["name"] for c in insp.get_unique_constraints(table)}
    names |= {i["name"] for i in insp.get_indexes(table)}
    return name in names


def upgrade() -> None:
    # ── agent_workflow_runs ─────────────────────────────────────────────
    if not _has_table("agent_workflow_runs"):
        op.create_table(
            "agent_workflow_runs",
            sa.Column("merchant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("run_id", sa.String(length=64), nullable=False),
            sa.Column("mode", sa.String(length=20), nullable=False, server_default="deep"),
            sa.Column(
                "status", sa.String(length=20), nullable=False, server_default="running"
            ),
            sa.Column("plan_fingerprint", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("plan", JSONB(), nullable=True),
            sa.Column("step_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("lease_owner", sa.String(length=64), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("errors", JSONB(), nullable=True),
            sa.Column("id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
            # One run id names exactly one cycle per tenant: re-using an id can
            # no longer silently fork a parallel cycle.
            sa.UniqueConstraint(
                "merchant_id", "run_id", name="uq_agent_workflow_runs_merchant_run"
            ),
        )
        op.create_index(
            op.f("ix_agent_workflow_runs_id"), "agent_workflow_runs", ["id"], unique=False
        )
        op.create_index(
            op.f("ix_agent_workflow_runs_merchant_id"),
            "agent_workflow_runs",
            ["merchant_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_agent_workflow_runs_run_id"), "agent_workflow_runs", ["run_id"], unique=False
        )
        op.create_index(
            op.f("ix_agent_workflow_runs_status"), "agent_workflow_runs", ["status"], unique=False
        )
        op.create_index(
            "ix_agent_workflow_runs_merchant_status",
            "agent_workflow_runs",
            ["merchant_id", "status"],
            unique=False,
        )

    # ── agent_runs: step identity + liveness ────────────────────────────
    _add_column(
        "agent_runs", sa.Column("workflow_id", UUID(as_uuid=True), nullable=True)
    )
    _add_column("agent_runs", sa.Column("step_key", sa.String(length=160), nullable=True))
    _add_column("agent_runs", sa.Column("step_index", sa.Integer(), nullable=True))
    _add_column(
        "agent_runs",
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
    )
    _add_column(
        "agent_runs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True)
    )
    # status values grew from (running, completed, failed, skipped) to include
    # partially_completed, blocked and interrupted.
    _widen_agent_run_status()

    if "workflow_id" in _columns("agent_runs"):
        op.create_index(
            op.f("ix_agent_runs_workflow_id"), "agent_runs", ["workflow_id"], unique=False
        )
        op.create_foreign_key(
            "fk_agent_runs_workflow_id",
            "agent_runs",
            "agent_workflow_runs",
            ["workflow_id"],
            ["id"],
            ondelete="CASCADE",
        )
    if not _has_constraint("agent_runs", "uq_agent_runs_workflow_step_attempt"):
        op.create_unique_constraint(
            "uq_agent_runs_workflow_step_attempt",
            "agent_runs",
            ["workflow_id", "step_key", "attempt"],
        )

    # ── agent_actions: idempotency ──────────────────────────────────────
    _add_column(
        "agent_actions", sa.Column("idempotency_key", sa.String(length=64), nullable=True)
    )
    _add_column(
        "agent_actions", sa.Column("workflow_run_id", UUID(as_uuid=True), nullable=True)
    )
    if "workflow_run_id" in _columns("agent_actions") and _has_table(
        "agent_workflow_runs"
    ):
        op.create_foreign_key(
            "fk_agent_actions_workflow_run_id",
            "agent_actions",
            "agent_workflow_runs",
            ["workflow_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if not _has_constraint("agent_actions", "uq_agent_actions_merchant_idempotency"):
        op.create_unique_constraint(
            "uq_agent_actions_merchant_idempotency",
            "agent_actions",
            ["merchant_id", "idempotency_key"],
        )


def _widen_agent_run_status() -> None:
    """Drop and recreate agent_runs.status so longer values fit.

    ``partially_completed`` (20 chars) is longer than the original VARCHAR(20)
    boundary is comfortable with alongside other values, so the column is
    rebuilt at 24. Data is preserved by ALTER ... TYPE on PostgreSQL.
    """
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.alter_column(
        "agent_runs",
        "status",
        type_=sa.String(length=24),
        existing_type=sa.String(length=20),
        existing_nullable=False,
    )


def downgrade() -> None:
    if _has_constraint("agent_actions", "uq_agent_actions_merchant_idempotency"):
        op.drop_constraint(
            "uq_agent_actions_merchant_idempotency", "agent_actions", type_="unique"
        )
    if _columns("agent_actions") and "workflow_run_id" in _columns("agent_actions"):
        op.drop_constraint(
            "fk_agent_actions_workflow_run_id", "agent_actions", type_="foreignkey"
        )
        op.drop_column("agent_actions", "workflow_run_id")
        op.drop_column("agent_actions", "idempotency_key")

    if _has_constraint("agent_runs", "uq_agent_runs_workflow_step_attempt"):
        op.drop_constraint(
            "uq_agent_runs_workflow_step_attempt", "agent_runs", type_="unique"
        )
    if _columns("agent_runs") and "workflow_id" in _columns("agent_runs"):
        op.drop_constraint("fk_agent_runs_workflow_id", "agent_runs", type_="foreignkey")
        op.drop_index(op.f("ix_agent_runs_workflow_id"), table_name="agent_runs")
        op.drop_column("agent_runs", "heartbeat_at")
        op.drop_column("agent_runs", "attempt")
        op.drop_column("agent_runs", "step_index")
        op.drop_column("agent_runs", "step_key")
        op.drop_column("agent_runs", "workflow_id")

    if _has_table("agent_workflow_runs"):
        op.drop_index("ix_agent_workflow_runs_merchant_status", table_name="agent_workflow_runs")
        op.drop_index(op.f("ix_agent_workflow_runs_status"), table_name="agent_workflow_runs")
        op.drop_index(op.f("ix_agent_workflow_runs_run_id"), table_name="agent_workflow_runs")
        op.drop_index(op.f("ix_agent_workflow_runs_merchant_id"), table_name="agent_workflow_runs")
        op.drop_index(op.f("ix_agent_workflow_runs_id"), table_name="agent_workflow_runs")
        op.drop_table("agent_workflow_runs")
