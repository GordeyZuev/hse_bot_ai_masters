"""Rename deadlines->tasks; users/subjects column updates

Revision ID: 013
Revises: 012
Create Date: 2025-11-04 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "013"
down_revision: str | Sequence[str] | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()

    # 1) deadlines -> tasks, and last_updated -> updated_at
    if "deadlines" in tables and "tasks" not in tables:
        op.rename_table("deadlines", "tasks")
        # Обновляем список таблиц после переименования
        tables = inspector.get_table_names()
    elif "tasks" in tables:
        # Таблица уже переименована, пропускаем переименование
        pass

    # Проверяем и переименовываем колонку last_updated -> updated_at
    if "tasks" in tables:
        tasks_columns = [col["name"] for col in inspector.get_columns("tasks")]
        if "last_updated" in tasks_columns and "updated_at" not in tasks_columns:
            with op.batch_alter_table("tasks", schema=None) as batch_op:
                batch_op.alter_column(
                    "last_updated",
                    new_column_name="updated_at",
                    existing_type=sa.DateTime(timezone=True),
                )

        # Rename indexes for consistency
        dialect_name = conn.dialect.name
        if dialect_name == "postgresql":
            # Получаем список всех индексов в базе данных
            result = conn.execute(sa.text(
                "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
            ))
            all_indexes = {row[0] for row in result}

            # Переименовываем индексы только если исходный существует, а целевой - нет
            index_mappings = [
                ("idx_deadlines_subject_id", "idx_tasks_subject_id"),
                ("idx_deadlines_soft_ts", "idx_tasks_soft_ts"),
                ("idx_deadlines_hard_ts", "idx_tasks_hard_ts"),
            ]

            for old_name, new_name in index_mappings:
                if old_name in all_indexes and new_name not in all_indexes:
                    op.execute(f"ALTER INDEX {old_name} RENAME TO {new_name}")

    # 2) users column renames and drop deprecated settings_version
    if "users" in tables:
        users_columns = [col["name"] for col in inspector.get_columns("users")]

        with op.batch_alter_table("users", schema=None) as batch_op:
            # subscribed_at -> created_at
            if "subscribed_at" in users_columns and "created_at" not in users_columns:
                batch_op.alter_column(
                    "subscribed_at",
                    new_column_name="created_at",
                    existing_type=sa.DateTime(timezone=True),
                )
            # last_activity_ts -> last_activity
            if "last_activity_ts" in users_columns and "last_activity" not in users_columns:
                batch_op.alter_column(
                    "last_activity_ts",
                    new_column_name="last_activity",
                    existing_type=sa.DateTime(timezone=True),
                )
            # drop settings_version
            if "settings_version" in users_columns:
                batch_op.drop_column("settings_version")

    # 3) subjects add updated_at
    if "subjects" in tables:
        subjects_columns = [col["name"] for col in inspector.get_columns("subjects")]
        if "updated_at" not in subjects_columns:
            with op.batch_alter_table("subjects", schema=None) as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "updated_at",
                        sa.DateTime(timezone=True),
                        server_default=sa.text("now()"),
                        nullable=True,
                    )
                )


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()

    # 3) subjects drop updated_at
    if "subjects" in tables:
        subjects_columns = [col["name"] for col in inspector.get_columns("subjects")]
        if "updated_at" in subjects_columns:
            with op.batch_alter_table("subjects", schema=None) as batch_op:
                batch_op.drop_column("updated_at")

    # 2) users column renames back and restore settings_version
    if "users" in tables:
        users_columns = [col["name"] for col in inspector.get_columns("users")]

        with op.batch_alter_table("users", schema=None) as batch_op:
            # created_at -> subscribed_at
            if "created_at" in users_columns and "subscribed_at" not in users_columns:
                batch_op.alter_column(
                    "created_at",
                    new_column_name="subscribed_at",
                    existing_type=sa.DateTime(timezone=True),
                )
            # last_activity -> last_activity_ts
            if "last_activity" in users_columns and "last_activity_ts" not in users_columns:
                batch_op.alter_column(
                    "last_activity",
                    new_column_name="last_activity_ts",
                    existing_type=sa.DateTime(timezone=True),
                )
            # restore settings_version
            if "settings_version" not in users_columns:
                batch_op.add_column(
                    sa.Column("settings_version", sa.Integer(), nullable=True, server_default="1")
                )

    # Rename indexes back (PostgreSQL only)
    dialect_name = conn.dialect.name
    if dialect_name == "postgresql":
        # Получаем список всех индексов в базе данных
        result = conn.execute(sa.text(
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
        ))
        all_indexes = {row[0] for row in result}

        # Переименовываем индексы обратно только если исходный существует, а целевой - нет
        index_mappings = [
            ("idx_tasks_subject_id", "idx_deadlines_subject_id"),
            ("idx_tasks_soft_ts", "idx_deadlines_soft_ts"),
            ("idx_tasks_hard_ts", "idx_deadlines_hard_ts"),
        ]

        for old_name, new_name in index_mappings:
            if old_name in all_indexes and new_name not in all_indexes:
                op.execute(f"ALTER INDEX {old_name} RENAME TO {new_name}")

    # 1) tasks -> deadlines, and updated_at -> last_updated
    if "tasks" in tables:
        tasks_columns = [col["name"] for col in inspector.get_columns("tasks")]
        if "updated_at" in tasks_columns and "last_updated" not in tasks_columns:
            with op.batch_alter_table("tasks", schema=None) as batch_op:
                batch_op.alter_column(
                    "updated_at",
                    new_column_name="last_updated",
                    existing_type=sa.DateTime(timezone=True),
                )

        if "deadlines" not in tables:
            op.rename_table("tasks", "deadlines")


