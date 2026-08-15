"""Add otp_logs table and streak_frozen_until + xp_boost_until to users

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-06 18:30:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # ── otp_logs table ────────────────────────────────────────────────────────
    op.create_table(
        "otp_logs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False, index=True),
        sa.Column("otp_hash", sa.String(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

def _add_column_if_not_exists(table: str, column: sa.Column) -> None:
    try:
        op.add_column(table, column)
    except Exception as e:
        if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
            pass
        else:
            raise

    # ── User columns ──────────────────────────────────────────────────────────
    _add_column_if_not_exists("users", sa.Column("streak_frozen_until", sa.DateTime(), nullable=True))
    _add_column_if_not_exists("users", sa.Column("xp_boost_until", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_table("otp_logs")
    op.drop_column("users", "streak_frozen_until")
    op.drop_column("users", "xp_boost_until")
