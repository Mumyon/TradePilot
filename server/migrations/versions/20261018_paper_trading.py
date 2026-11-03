"""Account preferences, immutable plans, candles and paper fills."""

import sqlalchemy as sa
from alembic import op

revision = "20261018_paper"
down_revision = "c060d541e2e4"
branch_labels = None
depends_on = None


def upgrade():
    # Preserve old pending orders and their original principal-only reservation.
    op.add_column(
        "orders",
        sa.Column("reserved_cash_won", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.execute(
        "UPDATE orders SET reserved_cash_won=quantity*limit_price_won "
        "WHERE status='accepted' AND side='buy'"
    )
    op.add_column(
        "users",
        sa.Column("cooldown_seconds", sa.BigInteger(), nullable=False, server_default="300"),
    )
    op.add_column(
        "users", sa.Column("trading_rules", sa.String(2000), nullable=False, server_default="")
    )
    # Legacy holdings have unknown acquisition cost. Never invent a historical P&L.
    op.add_column("holdings", sa.Column("cost_won", sa.BigInteger(), nullable=True))
    op.create_table(
        "trade_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("symbol", sa.String(16), sa.ForeignKey("symbols.symbol"), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("entry_condition", sa.String(1000), nullable=False),
        sa.Column("stop_loss_won", sa.BigInteger()),
        sa.Column("max_amount_won", sa.BigInteger(), nullable=False),
        sa.Column("split_order", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_trade_plans_user_id", "trade_plans", ["user_id"])
    op.create_table(
        "candles",
        sa.Column("symbol", sa.String(16), sa.ForeignKey("symbols.symbol"), primary_key=True),
        sa.Column("interval", sa.String(4), primary_key=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("source", sa.String(32), primary_key=True),
        *[
            sa.Column(name, sa.BigInteger(), nullable=False)
            for name in ["open_won", "high_won", "low_won", "close_won", "volume"]
        ],
        sa.Column("complete", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "fills",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "order_id", sa.String(36), sa.ForeignKey("orders.id"), nullable=False, unique=True
        ),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("symbol", sa.String(16), sa.ForeignKey("symbols.symbol"), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        *[
            sa.Column(name, sa.BigInteger(), nullable=False)
            for name in ["quantity", "price_won", "fee_won"]
        ],
        sa.Column("realized_pnl_won", sa.BigInteger()),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("quote_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_fills_user_id", "fills", ["user_id"])


def downgrade():
    op.drop_column("orders", "reserved_cash_won")
    for table in ["fills", "candles", "trade_plans"]:
        op.drop_table(table)
    op.drop_column("holdings", "cost_won")
    op.drop_column("users", "trading_rules")
    op.drop_column("users", "cooldown_seconds")
