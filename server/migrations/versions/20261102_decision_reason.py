"""Preserve optional manual deferral reasons separately from risk snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "20261102_decision_reason"
down_revision = "20261023_replay"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "order_checks",
        sa.Column("decision_reason", sa.String(1000), nullable=False, server_default=""),
    )


def downgrade():
    op.drop_column("order_checks", "decision_reason")
