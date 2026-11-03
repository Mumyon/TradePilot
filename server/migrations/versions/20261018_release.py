"""Keep post-trade review separate from immutable submission reasons."""

import sqlalchemy as sa
from alembic import op

revision = "20261018_release"
down_revision = "20261018_journal"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "orders", sa.Column("review_note", sa.String(2000), nullable=False, server_default="")
    )
    op.add_column(
        "orders", sa.Column("review_updated_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade():
    op.drop_column("orders", "review_updated_at")
    op.drop_column("orders", "review_note")
