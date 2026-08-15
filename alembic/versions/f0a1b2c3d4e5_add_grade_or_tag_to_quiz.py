"""add grade_or_tag column to quiz_questions and quiz_sessions

Revision ID: f0a1b2c3d4e5
Revises: e7f8a9b0c1d2
Create Date: 2026-07-13 23:50:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f0a1b2c3d4e5'
down_revision: Union[str, None] = 'e7f8a9b0c1d2'
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
    _add_column_if_not_exists('quiz_questions', sa.Column('grade_or_tag', sa.String(length=100), nullable=True, index=True))
    _add_column_if_not_exists('quiz_sessions', sa.Column('grade_or_tag', sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column('quiz_sessions', 'grade_or_tag')
    op.drop_column('quiz_questions', 'grade_or_tag')
