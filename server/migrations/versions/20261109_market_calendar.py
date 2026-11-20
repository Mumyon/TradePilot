"""Persist verified exchange calendars for paper execution."""

import sqlalchemy as sa
from alembic import op

revision = "20261109_market_calendar"
down_revision = "20261102_ai_reviews"
branch_labels = None
depends_on = None


def upgrade():
    # Earlier versions mixed REST snapshots and trade events in this cache.
    op.execute(
        "UPDATE quotes SET as_of = LEAST(as_of, CURRENT_TIMESTAMP - INTERVAL '1 day') "
        "WHERE source = 'toss_kr'"
    )
    op.create_table(
        "market_calendars",
        sa.Column("source", sa.String(32), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("market_calendars")
