"""Preserve observed feedback exposure and explicit decisions; do not backfill history."""

import sqlalchemy as sa
from alembic import op

revision = "20261022_feedback"
down_revision = "20261021_datasets"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "order_checks", sa.Column("origin", sa.String(16), nullable=False, server_default="legacy")
    )
    op.add_column("order_checks", sa.Column("presented_at", sa.DateTime(timezone=True)))
    op.add_column("order_checks", sa.Column("decided_at", sa.DateTime(timezone=True)))
    op.add_column("order_checks", sa.Column("submitted_order_id", sa.String(36)))


def downgrade():
    for name in ("submitted_order_id", "decided_at", "presented_at", "origin"):
        op.drop_column("order_checks", name)
