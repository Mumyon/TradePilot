"""Private research datasets, isolated from shared market candles."""

import sqlalchemy as sa
from alembic import op

revision = "20261021_datasets"
down_revision = "20261020_automation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "datasets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("symbol", sa.String(16), sa.ForeignKey("symbols.symbol"), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("data_kind", sa.String(16), nullable=False),
        sa.Column("rows", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_datasets_user_id", "datasets", ["user_id"])


def downgrade():
    op.drop_table("datasets")
