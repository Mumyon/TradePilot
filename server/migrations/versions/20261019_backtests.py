"""Isolated strategy configurations and immutable simulation results."""

import sqlalchemy as sa
from alembic import op

revision = "20261019_backtests"
down_revision = "20261018_release"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "strategies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_strategies_user_id", "strategies", ["user_id"])
    op.create_table(
        "backtests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("strategy_id", sa.String(36), sa.ForeignKey("strategies.id"), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_backtests_user_id", "backtests", ["user_id"])


def downgrade():
    op.drop_table("backtests")
    op.drop_table("strategies")
