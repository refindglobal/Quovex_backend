"""add referral_bonus_paid column

Revision ID: f325c222589e
Revises: 2a3b4c5d6e7f
Create Date: 2026-07-13 16:59:07.997725
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'f325c222589e'
down_revision: Union[str, None] = '2a3b4c5d6e7f'
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
    _add_column_if_not_exists('users', sa.Column('referral_bonus_paid', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    op.drop_column('users', 'referral_bonus_paid')
