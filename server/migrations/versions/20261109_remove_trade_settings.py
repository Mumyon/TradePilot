"""Remove live paper account trading preferences and their stored values."""

import sqlalchemy as sa
from alembic import op

revision = "20261109_remove_trade_settings"
down_revision = "20261109_market_calendar"
branch_labels = None
depends_on = None

FIELDS = [
    "order_limit_won",
    "daily_loss_limit_won",
    "cooldown_seconds",
    "trading_rules",
    "trading_paused",
]


def upgrade():
    # PostgreSQL removes the local check constraint depending on these columns.
    for field in FIELDS:
        op.drop_column("users", field)


def downgrade():
    # Removed personal settings cannot be recovered; downgrade restores defaults.
    for field in ["order_limit_won", "daily_loss_limit_won"]:
        op.add_column(
            "users", sa.Column(field, sa.BigInteger(), nullable=False, server_default="1000000")
        )
    op.add_column(
        "users",
        sa.Column("cooldown_seconds", sa.BigInteger(), nullable=False, server_default="300"),
    )
    op.add_column(
        "users", sa.Column("trading_rules", sa.String(2000), nullable=False, server_default="")
    )
    op.add_column(
        "users",
        sa.Column("trading_paused", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_check_constraint(
        "ck_users_legacy_trade_limits", "users", "order_limit_won > 0 AND daily_loss_limit_won > 0"
    )
