"""durable analysis cancellation

Fixes: "Stop" did not stop anything.

The dashboard offered a Stop control that only suspended frontend polling --
its own copy said "Backend analysis continues" -- and the orchestrator had no
cancellation concept at all. There was also no way to answer "is a run really
active?", so an orphaned ``running`` row left by a dead worker was reported as
live forever.

What this adds
--------------
``agent_workflow_runs.cancel_requested_at``
    A durable, cross-process cancellation flag. The cancel endpoint stamps it;
    the orchestrator polls it between steps. Deliberately persisted rather than
    held in memory: the worker usually runs in a different process from the one
    that received the request, and an in-memory flag would be invisible to it
    and lost on any restart.

``cancelled`` status
    Reuses the vocabulary ``product_agi`` already uses for its own runs, so no
    new status vocabulary is invented. Both status columns are already
    VARCHAR(24) and ``cancelled`` is 9 characters, so NO widening is required.

Migration safety
----------------
* Guarded, so re-running is a no-op.
* Nullable column, no backfill: historical rows have NULL, which correctly
  means "never cancelled".
* No historical row is deleted or rewritten.

Revision ID: f6b2c4d8e015
Revises: e5a1b3c7d904
Create Date: 2026-10-17

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f6b2c4d8e015"
down_revision = "e5a1b3c7d904"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if "cancel_requested_at" not in _columns("agent_workflow_runs"):
        op.add_column(
            "agent_workflow_runs",
            sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    if "cancel_requested_at" in _columns("agent_workflow_runs"):
        op.drop_column("agent_workflow_runs", "cancel_requested_at")
