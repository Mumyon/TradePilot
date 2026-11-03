"""Prediction provenance/outcomes and order-check decisions."""

import sqlalchemy as sa
from alembic import op

revision = "20261018_journal"
down_revision = "20261018_risk"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "order_checks",
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_order_checks_created_at", "order_checks", ["created_at"])
    op.add_column(
        "order_checks",
        sa.Column("decision", sa.String(16), nullable=False, server_default="pending"),
    )
    op.execute("UPDATE order_checks SET decision='legacy' WHERE consumed=true")
    op.create_table(
        "prediction_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("symbol", sa.String(16), sa.ForeignKey("symbols.symbol"), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("base_price_won", sa.BigInteger(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("outcome", sa.JSON(), nullable=True),
        sa.UniqueConstraint("symbol", "as_of", "model_version", name="uq_prediction_bar_model"),
    )
    op.create_index("ix_prediction_records_symbol", "prediction_records", ["symbol"])
    op.create_index("ix_prediction_records_target_at", "prediction_records", ["target_at"])


def downgrade():
    op.drop_table("prediction_records")
    op.drop_index("ix_order_checks_created_at", table_name="order_checks")
    op.drop_column("order_checks", "created_at")
    op.drop_column("order_checks", "decision")
