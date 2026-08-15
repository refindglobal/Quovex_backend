"""add delivery address columns to rewards table

Revision ID: d6e7f8a9b0c1
Revises: b2c3d4e5f6a7
Create Date: 2026-07-13 23:45:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'd6e7f8a9b0c1'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
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
    _add_column_if_not_exists('rewards', sa.Column('delivery_address_line1', sa.String(length=255), nullable=True))
    _add_column_if_not_exists('rewards', sa.Column('delivery_address_line2', sa.String(length=255), nullable=True))
    _add_column_if_not_exists('rewards', sa.Column('delivery_city', sa.String(length=100), nullable=True))
    _add_column_if_not_exists('rewards', sa.Column('delivery_state', sa.String(length=100), nullable=True))
    _add_column_if_not_exists('rewards', sa.Column('delivery_pincode', sa.String(length=20), nullable=True))
    _add_column_if_not_exists('rewards', sa.Column('delivery_landmark', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('rewards', 'delivery_landmark')
    op.drop_column('rewards', 'delivery_pincode')
    op.drop_column('rewards', 'delivery_state')
    op.drop_column('rewards', 'delivery_city')
    op.drop_column('rewards', 'delivery_address_line2')
    op.drop_column('rewards', 'delivery_address_line1')
