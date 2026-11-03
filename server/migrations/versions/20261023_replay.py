"""Private, immutable case snapshots and isolated historical paper sessions."""

import sqlalchemy as sa
from alembic import op

revision = "20261023_replay"
down_revision = "20261022_feedback"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "replay_cases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("rows", sa.JSON(), nullable=False),
        sa.Column("artifact", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_replay_cases_user_id", "replay_cases", ["user_id"])
    op.create_table(
        "replay_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("replay_cases.id"), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_replay_runs_user_id", "replay_runs", ["user_id"])
    op.create_index("ix_replay_runs_case_id", "replay_runs", ["case_id"])


def downgrade():
    op.drop_table("replay_runs")
    op.drop_table("replay_cases")
