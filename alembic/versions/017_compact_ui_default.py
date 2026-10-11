"""Use the dependable compact deadline view as the default."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "017"
down_revision: str | Sequence[str] | None = "016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Rich was the old implicit default, so existing rows do not represent a
    # deliberate opt-in. Keep it available, but require users to choose it.
    op.execute(
        "UPDATE user_notification_settings SET display_mode = 'compact' WHERE display_mode = 'rich'"
    )
    op.alter_column(
        "user_notification_settings",
        "display_mode",
        existing_type=sa.Text(),
        server_default="compact",
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "user_notification_settings",
        "display_mode",
        existing_type=sa.Text(),
        server_default="rich",
        existing_nullable=False,
    )
