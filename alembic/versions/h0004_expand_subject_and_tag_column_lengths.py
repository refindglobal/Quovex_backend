"""expand subject, exam_tag and grade_or_tag column lengths

Revision ID: h0004
Revises: h0003
Create Date: 2026-08-16
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'h0004'
down_revision: Union[str, None] = 'h0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect_name = conn.dialect.name

    if dialect_name == "postgresql":
        op.execute("ALTER TABLE quiz_questions ALTER COLUMN subject TYPE VARCHAR(500);")
        op.execute("ALTER TABLE quiz_questions ALTER COLUMN exam_tag TYPE VARCHAR(255);")
        op.execute("ALTER TABLE quiz_questions ALTER COLUMN grade_or_tag TYPE VARCHAR(255);")
        op.execute("ALTER TABLE quiz_sessions ALTER COLUMN subject TYPE VARCHAR(500);")
        op.execute("ALTER TABLE quiz_sessions ALTER COLUMN exam_tag TYPE VARCHAR(255);")
        op.execute("ALTER TABLE quiz_sessions ALTER COLUMN grade_or_tag TYPE VARCHAR(255);")
        op.execute("ALTER TABLE topics ALTER COLUMN name TYPE VARCHAR(500);")
        op.execute("ALTER TABLE topics ALTER COLUMN subject TYPE VARCHAR(500);")
        op.execute("ALTER TABLE doubts ALTER COLUMN subject TYPE VARCHAR(500);")
    else:
        # SQLite or other DBs (SQLite handles arbitrary length in VARCHAR)
        pass


def downgrade() -> None:
    pass
