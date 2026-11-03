"""Opt-in synthetic paper strategy execution and per-bar audit ledger."""

import sqlalchemy as sa
from alembic import op

revision = "20261020_automation"
down_revision = "20261019_backtests"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "automations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "strategy_id",
            sa.String(36),
            sa.ForeignKey("strategies.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("symbol", sa.String(16), sa.ForeignKey("symbols.symbol"), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("budget_won", sa.BigInteger(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_bar", sa.DateTime(timezone=True)),
        sa.Column("message", sa.String(1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_automations_user_id", "automations", ["user_id"])
    op.create_table(
        "automation_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("automation_id", sa.String(36), sa.ForeignKey("automations.id"), nullable=False),
        sa.Column("bar_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("signal", sa.String(8), nullable=False),
        sa.Column("message", sa.String(1000), nullable=False),
        sa.Column("order_id", sa.String(36), sa.ForeignKey("orders.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("automation_id", "bar_at", name="uq_automation_bar"),
    )
    op.create_index("ix_automation_events_automation_id", "automation_events", ["automation_id"])


def downgrade():
    op.drop_table("automation_events")
    op.drop_table("automations")
