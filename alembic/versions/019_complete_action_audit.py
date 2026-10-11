"""Keep interaction history even before user creation and after user deletion."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "019"
down_revision: str | Sequence[str] | None = "018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "user_action_events_user_id_fkey", "user_action_events", type_="foreignkey"
    )
    op.add_column("user_action_events", sa.Column("chat_id", sa.BigInteger()))
    op.add_column("user_action_events", sa.Column("message_id", sa.BigInteger()))
    op.add_column("user_action_events", sa.Column("outcome", sa.Text()))
    op.create_index(
        "ix_user_action_events_chat_time",
        "user_action_events",
        ["chat_id", "occurred_at"],
    )
    op.create_index(
        "ix_user_action_events_occurred_at", "user_action_events", ["occurred_at"]
    )


def downgrade() -> None:
    # Pre-registration events may reference users that never existed.
    op.execute(
        "DELETE FROM user_action_events e WHERE NOT EXISTS "
        "(SELECT 1 FROM users u WHERE u.tg_user_id = e.user_id)"
    )
    op.drop_index("ix_user_action_events_occurred_at", table_name="user_action_events")
    op.drop_index("ix_user_action_events_chat_time", table_name="user_action_events")
    op.drop_column("user_action_events", "outcome")
    op.drop_column("user_action_events", "message_id")
    op.drop_column("user_action_events", "chat_id")
    op.create_foreign_key(
        "user_action_events_user_id_fkey",
        "user_action_events",
        "users",
        ["user_id"],
        ["tg_user_id"],
        ondelete="CASCADE",
    )
