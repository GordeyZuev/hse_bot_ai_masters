"""Remove outdated tables

Revision ID: 003
Revises: 002
Create Date: 2025-09-07 16:28:39.480573

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: str | Sequence[str] | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""

    # Drop outdated notification_log table (replaced by scheduled_notifications)
    op.drop_index(
        "idx_notification_log_user_id", table_name="notification_log", if_exists=True
    )
    op.drop_index(
        "idx_notification_log_status_scheduled",
        table_name="notification_log",
        if_exists=True,
    )
    op.drop_table("notification_log", if_exists=True)

    # Drop outdated user_notifications table (replaced by user_notification_settings)
    op.drop_table("user_notifications", if_exists=True)


def downgrade() -> None:
    """Downgrade schema."""

    # Recreate user_notifications table
    op.create_table(
        "user_notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("offset_value", sa.Integer(), nullable=False),
        sa.Column("offset_unit", sa.Text(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("notification_number", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "last_modified",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.CheckConstraint("offset_value >= 0", name="check_offset_positive"),
        sa.CheckConstraint(
            "offset_unit IN ('days', 'hours', 'minutes')",
            name="check_offset_unit_valid",
        ),
        sa.CheckConstraint(
            "notification_number IN (1, 2)", name="check_notification_number_valid"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.tg_user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "notification_number", name="unique_user_notification_number"
        ),
    )

    # Recreate notification_log table
    op.create_table(
        "notification_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("deadline_id", sa.Integer(), nullable=False),
        sa.Column("notification_type", sa.Text(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["deadline_id"], ["deadlines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.tg_user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "deadline_id",
            "notification_type",
            name="unique_notification_task",
        ),
    )
    op.create_index(
        "idx_notification_log_status_scheduled",
        "notification_log",
        ["status", "scheduled_for"],
        unique=False,
    )
    op.create_index(
        "idx_notification_log_user_id", "notification_log", ["user_id"], unique=False
    )
