"""phase6 authentication and multi-tenancy tables

Revision ID: a3f8c2d91e47
Revises: c714f19a0609
Create Date: 2026-08-26

Creates:
  - users            : human authentication principals (scrypt hashes only)
  - memberships      : user <-> merchant tenant isolation + role
Alters:
  - audit_events.merchant_id becomes nullable (platform-level events such as
    Razorpay webhook deliveries are not attributable to one merchant)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a3f8c2d91e47'
down_revision: Union[str, Sequence[str], None] = 'c714f19a0609'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('users',
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.String(length=512), nullable=False),
    sa.Column('full_name', sa.String(length=255), nullable=True),
    sa.Column('status', sa.String(length=20), server_default='active', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    # Uniqueness enforced by the unique index below (matches the ORM's
    # unique=True + index=True mapping); no duplicate table-level constraint.
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    op.create_table('memberships',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('merchant_id', sa.Uuid(), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='active', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['merchant_id'], ['merchants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'merchant_id', name='uq_membership_user_merchant')
    )
    op.create_index(op.f('ix_memberships_id'), 'memberships', ['id'], unique=False)
    op.create_index(op.f('ix_memberships_user_id'), 'memberships', ['user_id'], unique=False)
    op.create_index(op.f('ix_memberships_merchant_id'), 'memberships', ['merchant_id'], unique=False)

    # Platform-level audit events (e.g. webhook deliveries) have no single merchant.
    op.alter_column('audit_events', 'merchant_id',
                    existing_type=sa.Uuid(),
                    nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    # Re-attach orphaned platform events to nothing — refuse if any exist
    # so the NOT NULL restore can never silently destroy audit history.
    bind = op.get_bind()
    orphans = bind.execute(
        sa.text("SELECT count(*) FROM audit_events WHERE merchant_id IS NULL")
    ).scalar()
    if orphans:
        raise RuntimeError(
            f"Cannot downgrade: {orphans} audit_events row(s) have no merchant. "
            "Delete or reassign them first."
        )
    op.alter_column('audit_events', 'merchant_id',
                    existing_type=sa.Uuid(),
                    nullable=False)

    op.drop_index(op.f('ix_memberships_merchant_id'), table_name='memberships')
    op.drop_index(op.f('ix_memberships_user_id'), table_name='memberships')
    op.drop_index(op.f('ix_memberships_id'), table_name='memberships')
    op.drop_table('memberships')

    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_index(op.f('ix_users_id'), table_name='users')
    op.drop_table('users')
