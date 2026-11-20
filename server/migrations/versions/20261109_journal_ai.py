"""Allow AI reviews for either research runs or ordinary paper orders."""

import sqlalchemy as sa
from alembic import op

revision = "20261109_journal_ai"
down_revision = "20261109_remove_trade_settings"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("ai_reviews", "run_id", nullable=True)
    op.add_column(
        "ai_reviews",
        sa.Column(
            "order_id", sa.String(36), sa.ForeignKey("orders.id"), nullable=True, unique=True
        ),
    )
    op.create_check_constraint(
        "ck_review_target", "ai_reviews", "(run_id IS NULL) <> (order_id IS NULL)"
    )


def downgrade():
    op.execute("DELETE FROM ai_reviews WHERE order_id IS NOT NULL")
    op.drop_constraint("ck_review_target", "ai_reviews", type_="check")
    op.drop_column("ai_reviews", "order_id")
    op.alter_column("ai_reviews", "run_id", nullable=False)
