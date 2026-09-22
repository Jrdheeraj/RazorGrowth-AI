"""marketing agi analysis cycle linkage

Revision ID: d4e5f6a7b8c9
Revises: a7c9e2f41b08
Create Date: 2026-09-21 00:00:00.000000

Links MarketingAGI runs to the shared AI Team analysis cycle:
adds marketing_agi_runs.analysis_cycle_id (nullable), stamped with the
orchestrator_run_id of the AI Team cycle that started the run.
Standalone runs keep NULL. No data migration needed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "a7c9e2f41b08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "marketing_agi_runs",
        sa.Column("analysis_cycle_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_marketing_agi_runs_analysis_cycle_id",
        "marketing_agi_runs",
        ["analysis_cycle_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_marketing_agi_runs_analysis_cycle_id",
        table_name="marketing_agi_runs",
    )
    op.drop_column("marketing_agi_runs", "analysis_cycle_id")
