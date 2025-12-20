"""Add chat groups support

Revision ID: 004
Revises: 003
Create Date: 2025-10-27 17:48:03.012699

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: str | Sequence[str] | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create chat_groups table
    op.create_table(
        "chat_groups",
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("topic_id", sa.BigInteger(), nullable=True),
        sa.Column("chat_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("reminder1_offset", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("reminder1_unit", sa.Text(), nullable=False, server_default="days"),
        sa.Column("reminder2_offset", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reminder2_unit", sa.Text(), nullable=False, server_default="days"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chat_id"),
        sa.CheckConstraint("chat_type IN ('group', 'supergroup')", name="check_chat_type_valid"),
        sa.CheckConstraint("reminder1_offset >= 0", name="check_chat_reminder1_positive"),
        sa.CheckConstraint("reminder1_unit IN ('days', 'hours')", name="check_chat_reminder1_unit_valid"),
        sa.CheckConstraint("reminder2_offset >= 0", name="check_chat_reminder2_positive"),
        sa.CheckConstraint("reminder2_unit IN ('days', 'hours')", name="check_chat_reminder2_unit_valid"),
    )

    # Create chat_scheduled_notifications table
    op.create_table(
        "chat_scheduled_notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_group_id", sa.BigInteger(), nullable=False),
        sa.Column("deadline_id", sa.Integer(), nullable=False),
        sa.Column("deadline_type", sa.Text(), nullable=False),
        sa.Column("notification_number", sa.Integer(), nullable=False),
        sa.Column("original_deadline_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("planned_delivery_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="scheduled"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["chat_group_id"], ["chat_groups.chat_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["deadline_id"], ["deadlines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_group_id", "deadline_id", "deadline_type", "notification_number", name="unique_chat_deadline_notification"),
        sa.CheckConstraint("deadline_type IN ('soft', 'hard')", name="check_chat_deadline_type_valid"),
        sa.CheckConstraint("notification_number IN (1, 2)", name="check_chat_notif_number_valid"),
        sa.CheckConstraint("status IN ('scheduled', 'sent', 'cancelled', 'failed')", name="check_chat_status_valid"),
    )

    # Create indexes
    op.create_index("idx_chat_sched_notif_chat_status", "chat_scheduled_notifications", ["chat_group_id", "status"], unique=False)
    op.create_index("idx_chat_sched_notif_deadline", "chat_scheduled_notifications", ["deadline_id"], unique=False)
    op.create_index("idx_chat_sched_notif_delivery_time", "chat_scheduled_notifications", ["planned_delivery_time"], unique=False)
    op.create_index("idx_chat_sched_notif_status_time", "chat_scheduled_notifications", ["status", "planned_delivery_time"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop indexes
    op.drop_index("idx_chat_sched_notif_status_time", table_name="chat_scheduled_notifications")
    op.drop_index("idx_chat_sched_notif_delivery_time", table_name="chat_scheduled_notifications")
    op.drop_index("idx_chat_sched_notif_deadline", table_name="chat_scheduled_notifications")
    op.drop_index("idx_chat_sched_notif_chat_status", table_name="chat_scheduled_notifications")

    # Drop tables
    op.drop_table("chat_scheduled_notifications")
    op.drop_table("chat_groups")
