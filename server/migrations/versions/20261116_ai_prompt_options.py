"""Save per-account prompts for chart and order analysis."""

import sqlalchemy as sa
from alembic import op

revision = "20261116_ai_prompt_options"
down_revision = "20261112_decision_ai"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("chart_prompt", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("order_prompt", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("users", "order_prompt")
    op.drop_column("users", "chart_prompt")
