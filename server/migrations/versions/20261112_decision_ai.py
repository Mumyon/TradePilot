"""Store independent market analyses and replay order feedback."""

import sqlalchemy as sa
from alembic import op

revision = "20261112_decision_ai"
down_revision = "20261109_pretrade_ai"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ai_reviews", sa.Column("context_key", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_ai_reviews_context_key", "ai_reviews", ["context_key"])
    op.drop_constraint("ck_review_target", "ai_reviews", type_="check")
    op.create_check_constraint(
        "ck_review_target",
        "ai_reviews",
        "num_nonnulls(run_id, order_id, check_id, context_key) = 1",
    )


def downgrade():
    op.execute("DELETE FROM ai_reviews WHERE context_key IS NOT NULL")
    op.drop_constraint("ck_review_target", "ai_reviews", type_="check")
    op.create_check_constraint(
        "ck_review_target", "ai_reviews", "num_nonnulls(run_id, order_id, check_id) = 1"
    )
    op.drop_constraint("uq_ai_reviews_context_key", "ai_reviews", type_="unique")
    op.drop_column("ai_reviews", "context_key")
