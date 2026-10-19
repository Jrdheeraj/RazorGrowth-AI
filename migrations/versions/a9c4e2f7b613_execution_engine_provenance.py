"""workflow execution-engine provenance

Fixes: recovery resumed every interrupted cycle through the legacy step loop,
even when the cycle was created and executed by the LangGraph executor.

The two engines do not lay out every plan identically (LangGraph adds nodes the
legacy plan does not, and some modes stop at different points), so silently
switching engines mid-cycle could skip or duplicate work. Recovery must continue
a cycle on the engine that created it.

What this adds
--------------
``agent_workflow_runs.execution_engine``
    ``"langgraph"`` or ``"legacy"``. Written once, at cycle creation, and never
    changed: provenance is immutable, so a caller cannot switch an existing
    cycle to another executor.

    Execution metadata only -- no business data, and no backfill. Historical
    rows keep NULL, which means "predates provenance" and is recovered by the
    historical legacy path exactly as before. A value outside the known set is
    refused by ``resume()`` rather than guessed.

Migration safety
----------------
* Guarded, so re-running is a no-op.
* Nullable, no backfill, no historical row rewritten or deleted.
* Downgrade drops only this column.

Revision ID: a9c4e2f7b613
Revises: f6b2c4d8e015
Create Date: 2026-10-19

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a9c4e2f7b613"
down_revision = "f6b2c4d8e015"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if "execution_engine" not in _columns("agent_workflow_runs"):
        op.add_column(
            "agent_workflow_runs",
            sa.Column("execution_engine", sa.String(length=20), nullable=True),
        )


def downgrade() -> None:
    if "execution_engine" in _columns("agent_workflow_runs"):
        op.drop_column("agent_workflow_runs", "execution_engine")
