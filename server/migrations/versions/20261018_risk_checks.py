"""Behavior snapshots, machine-readable plans and quote history."""

import sqlalchemy as sa
from alembic import op

revision = "20261018_risk"
down_revision = "20261018_paper"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("trading_paused", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    for name in ["entry_min_won", "entry_max_won"]:
        op.add_column("trade_plans", sa.Column(name, sa.BigInteger(), nullable=True))
    for table in ["order_checks", "orders"]:
        op.add_column(
            table, sa.Column("analysis", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
        )
    op.add_column("orders", sa.Column("plan_id", sa.String(36), nullable=True))
    op.create_foreign_key("fk_orders_plan_id", "orders", "trade_plans", ["plan_id"], ["id"])
    op.add_column("orders", sa.Column("plan_group_id", sa.String(36), nullable=True))
    op.create_table(
        "quote_samples",
        sa.Column("symbol", sa.String(16), sa.ForeignKey("symbols.symbol"), primary_key=True),
        sa.Column("source", sa.String(32), primary_key=True),
        sa.Column("as_of", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("price_won", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_quote_samples_as_of", "quote_samples", ["as_of"])


def downgrade():
    op.drop_table("quote_samples")
    op.drop_constraint("fk_orders_plan_id", "orders", type_="foreignkey")
    op.drop_column("orders", "plan_group_id")
    op.drop_column("orders", "plan_id")
    for table in ["orders", "order_checks"]:
        op.drop_column(table, "analysis")
    for name in ["entry_min_won", "entry_max_won"]:
        op.drop_column("trade_plans", name)
    op.drop_column("users", "trading_paused")
