"""Store a small set of successful user actions for historical analytics."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "018"
down_revision: str | Sequence[str] | None = "017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_action_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.tg_user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_name", sa.Text(), nullable=False),
        sa.Column("surface", sa.Text()),
        sa.Column("subject_id", sa.Integer()),
        sa.Column("task_id", sa.Integer()),
        sa.Column(
            "details",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_user_action_events_user_time",
        "user_action_events",
        ["user_id", "occurred_at"],
    )
    op.create_index(
        "ix_user_action_events_name_time",
        "user_action_events",
        ["event_name", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_action_events_name_time", table_name="user_action_events")
    op.drop_index("ix_user_action_events_user_time", table_name="user_action_events")
    op.drop_table("user_action_events")
