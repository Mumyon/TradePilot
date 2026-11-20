"""Move ordinary ChatGPT feedback to pre-trade order checks."""

import sqlalchemy as sa
from alembic import op

revision = "20261109_pretrade_ai"
down_revision = "20261109_journal_ai"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_review_target", "ai_reviews", type_="check")
    op.add_column(
        "ai_reviews",
        sa.Column(
            "check_id", sa.String(36), sa.ForeignKey("order_checks.id"), nullable=True, unique=True
        ),
    )
    op.create_check_constraint(
        "ck_review_target", "ai_reviews", "num_nonnulls(run_id, order_id, check_id) = 1"
    )
    op.execute(
        "UPDATE ai_reviews SET status='failed', completed_at=CURRENT_TIMESTAMP, "
        'data=data::jsonb || \'{"error":"feature_moved"}\'::jsonb '
        "WHERE order_id IS NOT NULL AND status IN ('pending','generating')"
    )


def downgrade():
    op.execute("DELETE FROM ai_reviews WHERE check_id IS NOT NULL")
    op.drop_constraint("ck_review_target", "ai_reviews", type_="check")
    op.drop_column("ai_reviews", "check_id")
    op.create_check_constraint(
        "ck_review_target", "ai_reviews", "(run_id IS NULL) <> (order_id IS NULL)"
    )
