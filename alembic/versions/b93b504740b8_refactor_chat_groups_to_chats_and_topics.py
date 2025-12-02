"""refactor_chat_groups_to_chats_and_topics

Revision ID: b93b504740b8
Revises: f1a2b3c4d5e6
Create Date: 2025-12-02 02:22:38.173185

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import text

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b93b504740b8"
down_revision: str | Sequence[str] | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Добавляем mode в chat_groups
    op.add_column("chat_groups", sa.Column("mode", sa.Text(), nullable=True))
    op.execute(sa.text("UPDATE chat_groups SET mode = 'single'"))
    op.alter_column("chat_groups", "mode", nullable=False)
    op.execute(sa.text("ALTER TABLE chat_groups ALTER COLUMN mode DROP DEFAULT"))
    op.create_check_constraint(
        "check_chat_mode_valid",
        "chat_groups",
        "mode IN ('single', 'multi')"
    )

    # 2. Создаем таблицу chat_group_topics
    op.create_table(
        "chat_group_topics",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("topic_id", sa.BigInteger(), nullable=True),
        sa.Column("topic_title", sa.Text(), nullable=True),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("reminder1_offset", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("reminder1_unit", sa.Text(), nullable=False, server_default="days"),
        sa.Column("reminder2_offset", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reminder2_unit", sa.Text(), nullable=False, server_default="days"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["chat_id"], ["chat_groups.chat_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_id", "topic_id", name="unique_chat_topic"),
        sa.CheckConstraint("reminder1_offset >= 0", name="check_topic_reminder1_positive"),
        sa.CheckConstraint("reminder1_unit IN ('days', 'hours')", name="check_topic_reminder1_unit_valid"),
        sa.CheckConstraint("reminder2_offset >= 0", name="check_topic_reminder2_positive"),
        sa.CheckConstraint("reminder2_unit IN ('days', 'hours')", name="check_topic_reminder2_unit_valid"),
    )

    # 3. Мигрируем данные из chat_groups в chat_group_topics
    # Для каждой записи в chat_groups создаем запись в chat_group_topics
    op.execute(text("""
        INSERT INTO chat_group_topics (
            chat_id, topic_id, topic_title, subject_id,
            reminder1_offset, reminder1_unit,
            reminder2_offset, reminder2_unit,
            is_active, created_at
        )
        SELECT
            chat_id, topic_id, topic_title, subject_id,
            reminder1_offset, reminder1_unit,
            reminder2_offset, reminder2_unit,
            is_active, created_at
        FROM chat_groups
    """))

    # 4. Обновляем chat_scheduled_notifications
    # Добавляем chat_topic_id, chat_id и topic_id
    op.add_column("chat_scheduled_notifications", sa.Column("chat_topic_id", sa.Integer(), nullable=True))
    op.add_column("chat_scheduled_notifications", sa.Column("chat_id", sa.BigInteger(), nullable=True))
    op.add_column("chat_scheduled_notifications", sa.Column("topic_id", sa.BigInteger(), nullable=True))

    # Связываем уведомления с chat_group_topics по (chat_id, topic_id)
    # Сначала получаем topic_id из chat_groups для каждого уведомления
    op.execute(text("""
        UPDATE chat_scheduled_notifications csn
        SET
            chat_topic_id = (
                SELECT cgt.id
                FROM chat_group_topics cgt
                WHERE cgt.chat_id = csn.chat_group_id
                AND (
                    (cgt.topic_id IS NULL AND (SELECT cg.topic_id FROM chat_groups cg WHERE cg.chat_id = csn.chat_group_id) IS NULL)
                    OR cgt.topic_id = (SELECT cg.topic_id FROM chat_groups cg WHERE cg.chat_id = csn.chat_group_id)
                )
                LIMIT 1
            ),
            chat_id = csn.chat_group_id,
            topic_id = (
                SELECT cg.topic_id FROM chat_groups cg WHERE cg.chat_id = csn.chat_group_id
            )
        WHERE EXISTS (
            SELECT 1
            FROM chat_group_topics cgt
            WHERE cgt.chat_id = csn.chat_group_id
            AND (
                (cgt.topic_id IS NULL AND (SELECT cg.topic_id FROM chat_groups cg WHERE cg.chat_id = csn.chat_group_id) IS NULL)
                OR cgt.topic_id = (SELECT cg.topic_id FROM chat_groups cg WHERE cg.chat_id = csn.chat_group_id)
            )
        )
    """))

    # Проверяем, что все уведомления связаны с топиками
    # Если есть уведомления без связи, удаляем их (они невалидны)
    op.execute(text("""
        DELETE FROM chat_scheduled_notifications
        WHERE chat_topic_id IS NULL
    """))

    # Делаем chat_topic_id и chat_id NOT NULL после заполнения
    op.alter_column("chat_scheduled_notifications", "chat_topic_id", nullable=False)
    op.alter_column("chat_scheduled_notifications", "chat_id", nullable=False)

    # Добавляем FK для chat_topic_id
    op.create_foreign_key(
        "fk_chat_scheduled_notifications_chat_topic_id",
        "chat_scheduled_notifications",
        "chat_group_topics",
        ["chat_topic_id"],
        ["id"],
        ondelete="CASCADE"
    )

    # Обновляем уникальный constraint: добавляем topic_id
    op.drop_constraint("unique_chat_deadline_notification", "chat_scheduled_notifications", type_="unique")
    op.create_unique_constraint(
        "unique_chat_topic_deadline_notification",
        "chat_scheduled_notifications",
        ["chat_topic_id", "deadline_id", "deadline_type", "notification_number"]
    )

    # Удаляем старый FK для chat_group_id (если существует)
    op.execute(text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'chat_scheduled_notifications_chat_group_id_fkey'
            ) THEN
                ALTER TABLE chat_scheduled_notifications DROP CONSTRAINT chat_scheduled_notifications_chat_group_id_fkey;
            END IF;
        END $$;
    """))

    # Удаляем старую колонку chat_group_id (если существует)
    op.execute(text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'chat_scheduled_notifications'
                AND column_name = 'chat_group_id'
            ) THEN
                ALTER TABLE chat_scheduled_notifications DROP COLUMN chat_group_id;
            END IF;
        END $$;
    """))

    # Обновляем индексы
    op.execute(text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE indexname = 'idx_chat_sched_notif_chat_status'
            ) THEN
                DROP INDEX idx_chat_sched_notif_chat_status;
            END IF;
        END $$;
    """))
    op.create_index(
        "idx_chat_sched_notif_topic_status",
        "chat_scheduled_notifications",
        ["chat_topic_id", "status"],
        unique=False
    )

    # 5. Удаляем ненужные столбцы из chat_groups (но оставляем таблицу)
    op.drop_column("chat_groups", "topic_id")
    op.drop_column("chat_groups", "topic_title")
    op.drop_column("chat_groups", "subject_id")
    op.drop_column("chat_groups", "reminder1_offset")
    op.drop_column("chat_groups", "reminder1_unit")
    op.drop_column("chat_groups", "reminder2_offset")
    op.drop_column("chat_groups", "reminder2_unit")
    op.drop_column("chat_groups", "is_active")

    # Удаляем старые constraints (если они существуют)
    # Используем IF EXISTS через raw SQL, так как Alembic не поддерживает это напрямую
    op.execute(text("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'check_chat_reminder1_positive' AND conrelid = 'chat_groups'::regclass) THEN
                ALTER TABLE chat_groups DROP CONSTRAINT check_chat_reminder1_positive;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'check_chat_reminder1_unit_valid' AND conrelid = 'chat_groups'::regclass) THEN
                ALTER TABLE chat_groups DROP CONSTRAINT check_chat_reminder1_unit_valid;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'check_chat_reminder2_positive' AND conrelid = 'chat_groups'::regclass) THEN
                ALTER TABLE chat_groups DROP CONSTRAINT check_chat_reminder2_positive;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'check_chat_reminder2_unit_valid' AND conrelid = 'chat_groups'::regclass) THEN
                ALTER TABLE chat_groups DROP CONSTRAINT check_chat_reminder2_unit_valid;
            END IF;
        END $$;
    """))

    # Переименовываем колонку last_updated в updated_at в таблице tasks (если существует)
    op.execute(text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'tasks'
                AND column_name = 'last_updated'
            ) THEN
                ALTER TABLE tasks RENAME COLUMN last_updated TO updated_at;
            END IF;
        END $$;
    """))


def downgrade() -> None:
    """Downgrade schema."""
    # Восстанавливаем столбцы в chat_groups
    op.add_column("chat_groups", sa.Column("topic_id", sa.BigInteger(), nullable=True))
    op.add_column("chat_groups", sa.Column("topic_title", sa.Text(), nullable=True))
    op.add_column("chat_groups", sa.Column("subject_id", sa.Integer(), nullable=True))
    op.add_column("chat_groups", sa.Column("reminder1_offset", sa.Integer(), nullable=False, server_default="7"))
    op.add_column("chat_groups", sa.Column("reminder1_unit", sa.Text(), nullable=False, server_default="days"))
    op.add_column("chat_groups", sa.Column("reminder2_offset", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("chat_groups", sa.Column("reminder2_unit", sa.Text(), nullable=False, server_default="days"))
    op.add_column("chat_groups", sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"))

    # Восстанавливаем constraints
    op.create_check_constraint("check_chat_reminder1_positive", "chat_groups", "reminder1_offset >= 0")
    op.create_check_constraint("check_chat_reminder1_unit_valid", "chat_groups", "reminder1_unit IN ('days', 'hours')")
    op.create_check_constraint("check_chat_reminder2_positive", "chat_groups", "reminder2_offset >= 0")
    op.create_check_constraint("check_chat_reminder2_unit_valid", "chat_groups", "reminder2_unit IN ('days', 'hours')")

    # Мигрируем данные обратно (берем первую запись из chat_group_topics для каждого чата)
    op.execute(text("""
        UPDATE chat_groups cg
        SET
            topic_id = (SELECT topic_id FROM chat_group_topics WHERE chat_id = cg.chat_id LIMIT 1),
            topic_title = (SELECT topic_title FROM chat_group_topics WHERE chat_id = cg.chat_id LIMIT 1),
            subject_id = (SELECT subject_id FROM chat_group_topics WHERE chat_id = cg.chat_id LIMIT 1),
            reminder1_offset = (SELECT reminder1_offset FROM chat_group_topics WHERE chat_id = cg.chat_id LIMIT 1),
            reminder1_unit = (SELECT reminder1_unit FROM chat_group_topics WHERE chat_id = cg.chat_id LIMIT 1),
            reminder2_offset = (SELECT reminder2_offset FROM chat_group_topics WHERE chat_id = cg.chat_id LIMIT 1),
            reminder2_unit = (SELECT reminder2_unit FROM chat_group_topics WHERE chat_id = cg.chat_id LIMIT 1),
            is_active = (SELECT is_active FROM chat_group_topics WHERE chat_id = cg.chat_id LIMIT 1)
    """))

    # Восстанавливаем FK для subject_id
    op.create_foreign_key(
        "fk_chat_groups_subject_id",
        "chat_groups",
        "subjects",
        ["subject_id"],
        ["id"],
        ondelete="CASCADE"
    )

    # Обновляем chat_scheduled_notifications обратно
    op.drop_constraint("unique_chat_topic_deadline_notification", "chat_scheduled_notifications", type_="unique")
    op.drop_constraint("fk_chat_scheduled_notifications_chat_topic_id", "chat_scheduled_notifications", type_="foreignkey")
    op.drop_index("idx_chat_sched_notif_topic_status", table_name="chat_scheduled_notifications")

    # Восстанавливаем chat_group_id (если был удален)
    op.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'chat_scheduled_notifications'
                AND column_name = 'chat_group_id'
            ) THEN
                ALTER TABLE chat_scheduled_notifications ADD COLUMN chat_group_id BIGINT;
                UPDATE chat_scheduled_notifications SET chat_group_id = chat_id WHERE chat_group_id IS NULL;
                ALTER TABLE chat_scheduled_notifications ALTER COLUMN chat_group_id SET NOT NULL;
            END IF;
        END $$;
    """))

    # Восстанавливаем FK для chat_group_id
    op.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'chat_scheduled_notifications_chat_group_id_fkey'
            ) THEN
                ALTER TABLE chat_scheduled_notifications
                ADD CONSTRAINT chat_scheduled_notifications_chat_group_id_fkey
                FOREIGN KEY (chat_group_id) REFERENCES chat_groups(chat_id) ON DELETE CASCADE;
            END IF;
        END $$;
    """))

    op.create_index(
        "idx_chat_sched_notif_chat_status",
        "chat_scheduled_notifications",
        ["chat_group_id", "status"],
        unique=False
    )
    op.create_unique_constraint(
        "unique_chat_deadline_notification",
        "chat_scheduled_notifications",
        ["chat_group_id", "deadline_id", "deadline_type", "notification_number"]
    )
    op.drop_column("chat_scheduled_notifications", "chat_topic_id")
    op.drop_column("chat_scheduled_notifications", "chat_id")
    op.drop_column("chat_scheduled_notifications", "topic_id")

    # Удаляем таблицу chat_group_topics
    op.drop_table("chat_group_topics")

    # Удаляем mode из chat_groups
    op.drop_constraint("check_chat_mode_valid", "chat_groups", type_="check")
    op.drop_column("chat_groups", "mode")

    # Возвращаем переименование колонки updated_at обратно в last_updated (если существует)
    op.execute(text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'tasks'
                AND column_name = 'updated_at'
            ) THEN
                ALTER TABLE tasks RENAME COLUMN updated_at TO last_updated;
            END IF;
        END $$;
    """))
