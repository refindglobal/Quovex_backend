"""add reward_configs table + custom_reward_name and reward_image_url to rewards

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-13 23:30:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None



def _add_column_if_not_exists(table, column):
    try:
        _add_column_if_not_exists(table, column)
    except Exception as e:
        if 'duplicate column' in str(e).lower() or 'already exists' in str(e).lower():
            pass
        else:
            raise


def upgrade() -> None:
    op.create_table('reward_configs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('period_month', sa.String(length=7), nullable=False, index=True),
        sa.Column('track', sa.Enum('study', 'quiz', 'overall', name='leaderboardtrack'), nullable=False),
        sa.Column('position_label', sa.String(length=20), nullable=False),
        sa.Column('reward_name', sa.String(length=200), nullable=False),
        sa.Column('reward_type', sa.String(length=50), nullable=False),
        sa.Column('amount_usd', sa.Float(), nullable=True),
        sa.Column('image_url', sa.Text(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    _add_column_if_not_exists('rewards', sa.Column('custom_reward_name', sa.String(length=200), nullable=True))
    _add_column_if_not_exists('rewards', sa.Column('reward_image_url', sa.Text(), nullable=True))



def downgrade() -> None:
    op.drop_column('rewards', 'reward_image_url')
    op.drop_column('rewards', 'custom_reward_name')
    op.drop_table('reward_configs')
    # Cannot remove enum value in PostgreSQL, but downgrade can proceed
