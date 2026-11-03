"""Optional, post-pair ChatGPT reviews; separate from immutable replay state."""

import sqlalchemy as sa
from alembic import op

revision = "20261102_ai_reviews"
down_revision = "20261102_decision_reason"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ai_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id", sa.String(36), sa.ForeignKey("replay_runs.id"), unique=True, nullable=False
        ),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.BigInteger(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_ai_reviews_user_id", "ai_reviews", ["user_id"])
    op.create_index("ix_ai_reviews_status", "ai_reviews", ["status"])


def downgrade():
    op.drop_table("ai_reviews")
