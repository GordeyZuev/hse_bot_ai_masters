"""Add safe sync, display mode and reliable delivery fields.

Revision ID: 015
Revises: 014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "015"
down_revision: str | Sequence[str] | None = "014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_delivery_columns(table: str) -> None:
    op.add_column(
        table,
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(table, sa.Column("next_attempt_at", sa.DateTime(timezone=True)))
    op.add_column(table, sa.Column("claimed_at", sa.DateTime(timezone=True)))
    op.add_column(table, sa.Column("sent_at", sa.DateTime(timezone=True)))
    op.add_column(table, sa.Column("last_error", sa.Text()))


def upgrade() -> None:
    op.add_column(
        "subjects",
        sa.Column(
            "modules",
            postgresql.ARRAY(sa.SmallInteger()),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column("subjects", sa.Column("leap_url", sa.Text()))
    op.add_column("subjects", sa.Column("youtube_url", sa.Text()))
    op.add_column("subjects", sa.Column("yandex_disk_url", sa.Text()))
    op.add_column(
        "subjects",
        sa.Column(
            "is_archived", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column("subjects", sa.Column("archived_at", sa.DateTime(timezone=True)))
    op.add_column("subjects", sa.Column("last_synced_at", sa.DateTime(timezone=True)))
    op.execute(
        "UPDATE subjects SET youtube_url = yt_playlist_url WHERE youtube_url IS NULL"
    )
    op.create_index(
        "uq_subjects_sheet_subject_id_not_null",
        "subjects",
        ["sheet_subject_id"],
        unique=True,
        postgresql_where=sa.text("sheet_subject_id IS NOT NULL"),
    )
    op.create_index(
        "idx_subjects_active_archived", "subjects", ["is_active", "is_archived"]
    )

    op.add_column("tasks", sa.Column("source_sheet", sa.Text()))
    op.add_column(
        "tasks",
        sa.Column(
            "is_archived", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column("tasks", sa.Column("archived_at", sa.DateTime(timezone=True)))
    op.add_column("tasks", sa.Column("last_synced_at", sa.DateTime(timezone=True)))
    op.create_index(
        "idx_tasks_source_archived", "tasks", ["source_sheet", "is_archived"]
    )

    op.add_column(
        "user_notification_settings",
        sa.Column("display_mode", sa.Text(), nullable=False, server_default="rich"),
    )
    op.create_check_constraint(
        "check_display_mode_valid",
        "user_notification_settings",
        "display_mode IN ('rich', 'compact')",
    )

    for table in ("scheduled_notifications", "chat_scheduled_notifications"):
        _add_delivery_columns(table)

    op.drop_constraint("check_status_valid", "scheduled_notifications", type_="check")
    op.execute(
        "UPDATE scheduled_notifications SET status = 'retry', next_attempt_at = NOW() "
        "WHERE status = 'failed'"
    )
    op.create_check_constraint(
        "check_status_valid",
        "scheduled_notifications",
        "status IN ('scheduled', 'processing', 'retry', 'sent', 'cancelled', 'dead')",
    )
    op.drop_constraint(
        "check_chat_status_valid", "chat_scheduled_notifications", type_="check"
    )
    op.execute(
        "UPDATE chat_scheduled_notifications SET status = 'retry', next_attempt_at = NOW() "
        "WHERE status = 'failed'"
    )
    op.create_check_constraint(
        "check_chat_status_valid",
        "chat_scheduled_notifications",
        "status IN ('scheduled', 'processing', 'retry', 'sent', 'cancelled', 'dead')",
    )
    op.create_index(
        "uq_chat_group_topics_single_mode",
        "chat_group_topics",
        ["chat_id"],
        unique=True,
        postgresql_where=sa.text("topic_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_chat_group_topics_single_mode", table_name="chat_group_topics")
    op.drop_constraint(
        "check_chat_status_valid", "chat_scheduled_notifications", type_="check"
    )
    op.execute(
        "UPDATE chat_scheduled_notifications SET status = 'failed' "
        "WHERE status IN ('processing', 'retry', 'dead')"
    )
    op.create_check_constraint(
        "check_chat_status_valid",
        "chat_scheduled_notifications",
        "status IN ('scheduled', 'sent', 'cancelled', 'failed')",
    )
    op.drop_constraint("check_status_valid", "scheduled_notifications", type_="check")
    op.execute(
        "UPDATE scheduled_notifications SET status = 'failed' "
        "WHERE status IN ('processing', 'retry', 'dead')"
    )
    op.create_check_constraint(
        "check_status_valid",
        "scheduled_notifications",
        "status IN ('scheduled', 'sent', 'cancelled', 'failed')",
    )
    for table in ("chat_scheduled_notifications", "scheduled_notifications"):
        for column in (
            "last_error",
            "sent_at",
            "claimed_at",
            "next_attempt_at",
            "attempt_count",
        ):
            op.drop_column(table, column)

    op.drop_constraint(
        "check_display_mode_valid", "user_notification_settings", type_="check"
    )
    op.drop_column("user_notification_settings", "display_mode")
    op.drop_index("idx_tasks_source_archived", table_name="tasks")
    for column in ("last_synced_at", "archived_at", "is_archived", "source_sheet"):
        op.drop_column("tasks", column)
    op.drop_index("idx_subjects_active_archived", table_name="subjects")
    op.drop_index("uq_subjects_sheet_subject_id_not_null", table_name="subjects")
    for column in (
        "last_synced_at",
        "archived_at",
        "is_archived",
        "yandex_disk_url",
        "youtube_url",
        "leap_url",
        "modules",
    ):
        op.drop_column("subjects", column)
