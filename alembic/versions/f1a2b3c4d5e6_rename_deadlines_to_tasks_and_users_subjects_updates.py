"""rename deadlines->tasks; users/subjects column updates

Revision ID: f1a2b3c4d5e6
Revises: e3f1a2b4c5d6
Create Date: 2025-11-04
"""

import sqlalchemy as sa

from alembic import op


# revision identifiers, used by Alembic.
revision = "f1a2b3c4d5e6"
down_revision = "e3f1a2b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) deadlines -> tasks, and last_updated -> updated_at
    op.rename_table("deadlines", "tasks")

    with op.batch_alter_table("tasks", schema=None) as batch_op:
        if op.get_bind().dialect.name == "postgresql":
            batch_op.alter_column(
                "last_updated",
                new_column_name="updated_at",
                existing_type=sa.DateTime(timezone=True),
            )
        else:
            batch_op.alter_column(
                "last_updated",
                new_column_name="updated_at",
                existing_type=sa.DateTime(timezone=True),
            )

    # Rename indexes for consistency
    conn = op.get_bind()
    dialect_name = conn.dialect.name
    if dialect_name == "postgresql":
        op.execute("ALTER INDEX IF EXISTS idx_deadlines_subject_id RENAME TO idx_tasks_subject_id")
        op.execute("ALTER INDEX IF EXISTS idx_deadlines_soft_ts RENAME TO idx_tasks_soft_ts")
        op.execute("ALTER INDEX IF EXISTS idx_deadlines_hard_ts RENAME TO idx_tasks_hard_ts")

    # 2) users column renames and drop deprecated settings_version
    with op.batch_alter_table("users", schema=None) as batch_op:
        # subscribed_at -> created_at
        batch_op.alter_column(
            "subscribed_at",
            new_column_name="created_at",
            existing_type=sa.DateTime(timezone=True),
        )
        # last_activity_ts -> last_activity
        batch_op.alter_column(
            "last_activity_ts",
            new_column_name="last_activity",
            existing_type=sa.DateTime(timezone=True),
        )
        # drop settings_version
        batch_op.drop_column("settings_version")

    # 3) subjects add updated_at
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
    # 3) subjects drop updated_at
    with op.batch_alter_table("subjects", schema=None) as batch_op:
        batch_op.drop_column("updated_at")

    # 2) users column renames back and restore settings_version
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "created_at",
            new_column_name="subscribed_at",
            existing_type=sa.DateTime(timezone=True),
        )
        batch_op.alter_column(
            "last_activity",
            new_column_name="last_activity_ts",
            existing_type=sa.DateTime(timezone=True),
        )
        batch_op.add_column(
            sa.Column("settings_version", sa.Integer(), nullable=True, server_default="1")
        )

    # Rename indexes back (PostgreSQL only)
    conn = op.get_bind()
    dialect_name = conn.dialect.name
    if dialect_name == "postgresql":
        op.execute("ALTER INDEX IF EXISTS idx_tasks_subject_id RENAME TO idx_deadlines_subject_id")
        op.execute("ALTER INDEX IF EXISTS idx_tasks_soft_ts RENAME TO idx_deadlines_soft_ts")
        op.execute("ALTER INDEX IF EXISTS idx_tasks_hard_ts RENAME TO idx_deadlines_hard_ts")

    # 1) tasks -> deadlines, and updated_at -> last_updated
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.alter_column(
            "updated_at",
            new_column_name="last_updated",
            existing_type=sa.DateTime(timezone=True),
        )

    op.rename_table("tasks", "deadlines")


