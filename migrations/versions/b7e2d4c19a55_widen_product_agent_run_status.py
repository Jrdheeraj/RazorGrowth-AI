"""Widen ``product_agent_runs.status`` so every run status is storable.

WHY
---
``agents.product_agi.state.RunStatus`` contains ``approved_awaiting_execution``
(27 characters) but the column was created as ``VARCHAR(24)``. Every other
member fits; that one did not.

On Postgres the write raises ``StringDataRightTruncation``, which happened
inside ``product_action_sync`` AFTER a ``flush()``. The blanket
``except Exception`` around the mirror sync swallowed it and logged
"canonical state kept" — but the session was already in a failed-transaction
state, so the approval audit event was lost and the route's ``commit()``
raised ``PendingRollbackError`` → HTTP 500 and the approval rolled back.
Approving a Product Agent action was therefore broken in production while
every test passed, because SQLite does not enforce VARCHAR(n).

WHAT
----
Widen the column to 32 characters. Purely additive: every value already
persisted is at most 23 characters and is preserved verbatim.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b7e2d4c19a55"
down_revision = "f2a7c4e91b30"
branch_labels = None
depends_on = None

#: Longest ``RunStatus`` member: ``approved_awaiting_execution`` = 27 chars.
#: 32 leaves headroom without being unbounded.
STATUS_WIDTH = 32
PREVIOUS_WIDTH = 24


def upgrade() -> None:
    op.alter_column(
        "product_agent_runs",
        "status",
        type_=sa.String(STATUS_WIDTH),
        existing_type=sa.String(PREVIOUS_WIDTH),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Narrowing back would truncate a legitimate 27-character status, so the
    # downgrade is a no-op when any row no longer fits. Surfacing the data is
    # safer than destroying it; an operator who has already migrated those
    # rows away from that status can re-run this freely.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM product_agent_runs
                WHERE length(status) > {PREVIOUS_WIDTH}
            ) THEN
                ALTER TABLE product_agent_runs
                    ALTER COLUMN status TYPE VARCHAR({PREVIOUS_WIDTH});
            END IF;
        END $$;
        """
    )