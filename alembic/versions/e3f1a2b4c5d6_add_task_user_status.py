"""add task_user_status table

Revision ID: e3f1a2b4c5d6
Revises: 936938f0c3a2_add_chat_title_to_chat_groups
Create Date: 2025-11-03
"""

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op


# revision identifiers, used by Alembic.
revision = "e3f1a2b4c5d6"
down_revision = "936938f0c3a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Проверяем существование таблицы
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()
    
    if "task_user_status" not in tables:
        op.create_table(
            "task_user_status",
            sa.Column(
                "user_id",
                sa.BigInteger(),
                sa.ForeignKey("users.tg_user_id", ondelete="CASCADE"),
                primary_key=True,
                nullable=False,
            ),
            sa.Column(
                "deadline_id",
                sa.Integer(),
                sa.ForeignKey("deadlines.id", ondelete="CASCADE"),
                primary_key=True,
                nullable=False,
            ),
        )
        # Создаем индекс после создания таблицы
        op.create_index("ix_tus_deadline_id", "task_user_status", ["deadline_id"])
    else:
        # Проверяем существование индекса перед созданием
        indexes = [idx["name"] for idx in inspector.get_indexes("task_user_status")]
        if "ix_tus_deadline_id" not in indexes:
            op.create_index("ix_tus_deadline_id", "task_user_status", ["deadline_id"])


def downgrade() -> None:
    # Проверяем существование перед удалением
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()
    
    if "task_user_status" in tables:
        # Проверяем существование индекса перед удалением
        indexes = [idx["name"] for idx in inspector.get_indexes("task_user_status")]
        if "ix_tus_deadline_id" in indexes:
            op.drop_index("ix_tus_deadline_id", table_name="task_user_status")
        op.drop_table("task_user_status")


