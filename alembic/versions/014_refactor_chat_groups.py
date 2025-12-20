"""Refactor chat_groups to chats and topics

Revision ID: 014
Revises: 013
Create Date: 2025-12-02 02:22:38.173185

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import text

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "014"
down_revision: str | Sequence[str] | None = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Добавляем mode в chat_groups (если не существует)
    op.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'chat_groups'
                AND column_name = 'mode'
            ) THEN
                ALTER TABLE chat_groups ADD COLUMN mode TEXT;
                UPDATE chat_groups SET mode = 'single' WHERE mode IS NULL;
                ALTER TABLE chat_groups ALTER COLUMN mode SET NOT NULL;
            ELSE
                -- Если колонка уже существует, обновляем только NULL значения
                UPDATE chat_groups SET mode = 'single' WHERE mode IS NULL;
            END IF;
        END $$;
    """))

    # Добавляем constraint для mode (если не существует)
    op.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'check_chat_mode_valid'
                AND conrelid = 'chat_groups'::regclass
            ) THEN
                ALTER TABLE chat_groups ADD CONSTRAINT check_chat_mode_valid
                CHECK (mode IN ('single', 'multi'));
            END IF;
        END $$;
    """))

    # 2. Создаем таблицу chat_group_topics (если не существует)
    op.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_name = 'chat_group_topics'
            ) THEN
                CREATE TABLE chat_group_topics (
                    id SERIAL NOT NULL,
                    chat_id BIGINT NOT NULL,
                    topic_id BIGINT,
                    topic_title TEXT,
                    subject_id INTEGER NOT NULL,
                    reminder1_offset INTEGER DEFAULT 7 NOT NULL,
                    reminder1_unit TEXT DEFAULT 'days' NOT NULL,
                    reminder2_offset INTEGER DEFAULT 1 NOT NULL,
                    reminder2_unit TEXT DEFAULT 'days' NOT NULL,
                    is_active BOOLEAN DEFAULT true NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    PRIMARY KEY (id),
                    FOREIGN KEY(chat_id) REFERENCES chat_groups (chat_id) ON DELETE CASCADE,
                    FOREIGN KEY(subject_id) REFERENCES subjects (id) ON DELETE CASCADE,
                    CONSTRAINT unique_chat_topic UNIQUE (chat_id, topic_id),
                    CONSTRAINT check_topic_reminder1_positive CHECK (reminder1_offset >= 0),
                    CONSTRAINT check_topic_reminder1_unit_valid CHECK (reminder1_unit IN ('days', 'hours')),
                    CONSTRAINT check_topic_reminder2_positive CHECK (reminder2_offset >= 0),
                    CONSTRAINT check_topic_reminder2_unit_valid CHECK (reminder2_unit IN ('days', 'hours'))
                );
            END IF;
        END $$;
    """))

    # 3. Мигрируем данные из chat_groups в chat_group_topics
    # Для каждой записи в chat_groups создаем запись в chat_group_topics (если еще не мигрировано)
    op.execute(text("""
        INSERT INTO chat_group_topics (
            chat_id, topic_id, topic_title, subject_id,
            reminder1_offset, reminder1_unit,
            reminder2_offset, reminder2_unit,
            is_active, created_at
        )
        SELECT
            cg.chat_id, cg.topic_id, cg.topic_title, cg.subject_id,
            cg.reminder1_offset, cg.reminder1_unit,
            cg.reminder2_offset, cg.reminder2_unit,
            cg.is_active, cg.created_at
        FROM chat_groups cg
        WHERE NOT EXISTS (
            SELECT 1
            FROM chat_group_topics cgt
            WHERE cgt.chat_id = cg.chat_id
            AND (
                (cgt.topic_id IS NULL AND cg.topic_id IS NULL)
                OR cgt.topic_id = cg.topic_id
            )
        )
    """))

    # 4. Обновляем chat_scheduled_notifications
    # Добавляем chat_topic_id, chat_id и topic_id (если не существуют)
    op.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'chat_scheduled_notifications'
                AND column_name = 'chat_topic_id'
            ) THEN
                ALTER TABLE chat_scheduled_notifications ADD COLUMN chat_topic_id INTEGER;
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'chat_scheduled_notifications'
                AND column_name = 'chat_id'
            ) THEN
                ALTER TABLE chat_scheduled_notifications ADD COLUMN chat_id BIGINT;
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'chat_scheduled_notifications'
                AND column_name = 'topic_id'
            ) THEN
                ALTER TABLE chat_scheduled_notifications ADD COLUMN topic_id BIGINT;
            END IF;
        END $$;
    """))

    # Связываем уведомления с chat_group_topics по (chat_id, topic_id)
    # Обновляем только те записи, которые еще не были обновлены
    op.execute(text("""
        UPDATE chat_scheduled_notifications csn
        SET
            chat_topic_id = (
                SELECT cgt.id
                FROM chat_group_topics cgt
                WHERE cgt.chat_id = COALESCE(csn.chat_id, csn.chat_group_id)
                AND (
                    (cgt.topic_id IS NULL AND (SELECT cg.topic_id FROM chat_groups cg WHERE cg.chat_id = COALESCE(csn.chat_id, csn.chat_group_id)) IS NULL)
                    OR cgt.topic_id = (SELECT cg.topic_id FROM chat_groups cg WHERE cg.chat_id = COALESCE(csn.chat_id, csn.chat_group_id))
                )
                LIMIT 1
            ),
            chat_id = COALESCE(csn.chat_id, csn.chat_group_id),
            topic_id = (
                SELECT cg.topic_id FROM chat_groups cg WHERE cg.chat_id = COALESCE(csn.chat_id, csn.chat_group_id)
            )
        WHERE (csn.chat_topic_id IS NULL OR csn.chat_id IS NULL)
        AND EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'chat_scheduled_notifications'
            AND column_name = 'chat_group_id'
        )
        AND EXISTS (
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

    # Делаем chat_topic_id и chat_id NOT NULL после заполнения (если еще не NOT NULL)
    op.execute(text("""
        DO $$
        BEGIN
            -- Проверяем и устанавливаем NOT NULL для chat_topic_id
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'chat_scheduled_notifications'
                AND column_name = 'chat_topic_id'
                AND is_nullable = 'YES'
            ) THEN
                -- Удаляем записи с NULL перед установкой NOT NULL
                DELETE FROM chat_scheduled_notifications WHERE chat_topic_id IS NULL;
                ALTER TABLE chat_scheduled_notifications ALTER COLUMN chat_topic_id SET NOT NULL;
            END IF;

            -- Проверяем и устанавливаем NOT NULL для chat_id
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'chat_scheduled_notifications'
                AND column_name = 'chat_id'
                AND is_nullable = 'YES'
            ) THEN
                -- Удаляем записи с NULL перед установкой NOT NULL
                DELETE FROM chat_scheduled_notifications WHERE chat_id IS NULL;
                ALTER TABLE chat_scheduled_notifications ALTER COLUMN chat_id SET NOT NULL;
            END IF;
        END $$;
    """))

    # Добавляем FK для chat_topic_id (если не существует)
    op.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_chat_scheduled_notifications_chat_topic_id'
            ) THEN
                ALTER TABLE chat_scheduled_notifications
                ADD CONSTRAINT fk_chat_scheduled_notifications_chat_topic_id
                FOREIGN KEY (chat_topic_id) REFERENCES chat_group_topics(id) ON DELETE CASCADE;
            END IF;
        END $$;
    """))

    # Обновляем уникальный constraint: добавляем topic_id
    op.execute(text("""
        DO $$
        BEGIN
            -- Удаляем старый constraint, если существует
            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'unique_chat_deadline_notification'
                AND conrelid = 'chat_scheduled_notifications'::regclass
            ) THEN
                ALTER TABLE chat_scheduled_notifications DROP CONSTRAINT unique_chat_deadline_notification;
            END IF;

            -- Создаем новый constraint, если не существует
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'unique_chat_topic_deadline_notification'
                AND conrelid = 'chat_scheduled_notifications'::regclass
            ) THEN
                ALTER TABLE chat_scheduled_notifications
                ADD CONSTRAINT unique_chat_topic_deadline_notification
                UNIQUE (chat_topic_id, deadline_id, deadline_type, notification_number);
            END IF;
        END $$;
    """))

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
            -- Удаляем старый индекс, если существует
            IF EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE indexname = 'idx_chat_sched_notif_chat_status'
            ) THEN
                DROP INDEX idx_chat_sched_notif_chat_status;
            END IF;

            -- Создаем новый индекс, если не существует
            IF NOT EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE indexname = 'idx_chat_sched_notif_topic_status'
            ) THEN
                CREATE INDEX idx_chat_sched_notif_topic_status
                ON chat_scheduled_notifications(chat_topic_id, status);
            END IF;
        END $$;
    """))

    # 5. Удаляем ненужные столбцы из chat_groups (но оставляем таблицу)
    op.execute(text("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'chat_groups' AND column_name = 'topic_id') THEN
                ALTER TABLE chat_groups DROP COLUMN topic_id;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'chat_groups' AND column_name = 'topic_title') THEN
                ALTER TABLE chat_groups DROP COLUMN topic_title;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'chat_groups' AND column_name = 'subject_id') THEN
                ALTER TABLE chat_groups DROP COLUMN subject_id;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'chat_groups' AND column_name = 'reminder1_offset') THEN
                ALTER TABLE chat_groups DROP COLUMN reminder1_offset;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'chat_groups' AND column_name = 'reminder1_unit') THEN
                ALTER TABLE chat_groups DROP COLUMN reminder1_unit;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'chat_groups' AND column_name = 'reminder2_offset') THEN
                ALTER TABLE chat_groups DROP COLUMN reminder2_offset;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'chat_groups' AND column_name = 'reminder2_unit') THEN
                ALTER TABLE chat_groups DROP COLUMN reminder2_unit;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'chat_groups' AND column_name = 'is_active') THEN
                ALTER TABLE chat_groups DROP COLUMN is_active;
            END IF;
        END $$;
    """))

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
