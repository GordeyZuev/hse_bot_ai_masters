import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
from dotenv import load_dotenv
from sqlalchemy import and_, delete, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.models import (
    Base,
    ScheduledNotification,
    Subject,
    Task,
    User,
    UserActionEvent,
    UserNotificationSettings,
)
from src.utils import get_logger
from src.utils.time import utc_now


# Загружаем переменные окружения
load_dotenv("src/config/.env")
logger = get_logger()


class DatabaseManager:
    def __init__(self, auto_init: bool = False):
        # Базовые параметры БД
        self.db_name = os.getenv("DB_NAME", os.getenv("POSTGRES_DB", "hse_bot_db"))
        self.db_user = os.getenv("DB_USER", os.getenv("POSTGRES_USER", "postgres"))
        self.db_password = os.getenv(
            "DB_PASSWORD", os.getenv("POSTGRES_PASSWORD", "password")
        )
        self.db_host = os.getenv("DB_HOST", "localhost")
        self.db_port = os.getenv("DB_PORT", "5432")

        # Генерируем DATABASE_URL автоматически
        self.database_url = os.getenv("DATABASE_URL")
        if not self.database_url:
            self.database_url = f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
            # Логируем без пароля для безопасности
            safe_url = f"postgresql+asyncpg://{self.db_user}:***@{self.db_host}:{self.db_port}/{self.db_name}"
            logger.info(f"DATABASE_URL сгенерирован автоматически: {safe_url}")

        self.engine = None
        self.async_session = None
        self.auto_init = auto_init
        self.initialized = False
        self._init_lock = asyncio.Lock()
        logger.info(
            f"Менеджер базы данных инициализирован для БД: {self.db_name} на {self.db_host}:{self.db_port}"
        )

    async def __aenter__(self):
        if not self.engine:
            await self.ensure_database_exists()
            await self.create_engine()
        if self.auto_init and not self.initialized:
            await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def ensure_database_exists(self):
        """Создает базу данных, если она не существует"""
        max_retries = 5
        retry_delay = 2

        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Попытка подключения к PostgreSQL (попытка {attempt + 1}/{max_retries})"
                )

                conn = await asyncpg.connect(
                    host=self.db_host,
                    port=int(self.db_port),
                    user=self.db_user,
                    password=self.db_password,
                    database="postgres",
                    timeout=10,
                )

                result = await conn.fetchval(
                    "SELECT 1 FROM pg_database WHERE datname = $1", self.db_name
                )

                if not result:
                    await conn.execute(f'CREATE DATABASE "{self.db_name}"')
                    logger.info(f"База данных '{self.db_name}' создана")
                else:
                    logger.info(f"База данных '{self.db_name}' уже существует")

                await conn.close()
                return

            except Exception as e:
                logger.error(f"Ошибка создания БД (попытка {attempt + 1}): {e}")
                if attempt == max_retries - 1:
                    logger.critical(
                        f"Не удалось подключиться к PostgreSQL после {max_retries} попыток"
                    )
                    raise

                logger.info(f"Повторная попытка через {retry_delay} секунд...")
                await asyncio.sleep(retry_delay)

    async def create_engine(self):
        """Создает движок SQLAlchemy после того, как база данных существует"""
        self.engine = create_async_engine(
            self.database_url,
            echo=False,
            pool_pre_ping=True,
            pool_recycle=3600,
            pool_size=10,
            max_overflow=20,
            pool_timeout=30,
        )

        self.async_session = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def ensure_initialized(self):
        """Гарантирует, что БД инициализирована"""
        async with self._init_lock:
            if self.initialized:
                return

            if not self.engine:
                await self.ensure_database_exists()
                await self.create_engine()

            tables_exist = await self.check_tables_exist()
            is_production = os.getenv("ENVIRONMENT", "development") == "production"

            if not tables_exist:
                if is_production:
                    raise RuntimeError(
                        "Схема БД отсутствует: сначала выполните alembic upgrade head"
                    )
                logger.warning("Таблицы отсутствуют, создаём dev-схему БД...")
                await self.initialize()
            else:
                await self.verify_schema_version()
                self.initialized = True
                logger.info("Схема БД соответствует миграциям")

    async def verify_schema_version(self) -> None:
        """Reject a stamped or outdated schema before polling and jobs start."""
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        root = Path(__file__).resolve().parents[3]
        expected = ScriptDirectory.from_config(
            Config(str(root / "alembic.ini"))
        ).get_current_head()
        required = {
            "subjects": {
                "modules",
                "leap_url",
                "youtube_url",
                "yandex_disk_url",
                "is_archived",
            },
            "tasks": {"source_sheet", "is_archived"},
            "user_notification_settings": {"display_mode"},
            "scheduled_notifications": {"attempt_count", "next_attempt_at"},
            "chat_scheduled_notifications": {"attempt_count", "next_attempt_at"},
            "user_action_events": {
                "user_id",
                "event_name",
                "occurred_at",
                "chat_id",
                "message_id",
                "outcome",
            },
        }
        async with self.engine.connect() as connection:
            has_version = await connection.scalar(
                text("SELECT to_regclass('alembic_version')")
            )
            current = (
                await connection.scalar(text("SELECT version_num FROM alembic_version"))
                if has_version
                else None
            )
            columns = (
                await connection.execute(
                    text(
                        "SELECT table_name, column_name FROM information_schema.columns "
                        "WHERE table_schema = current_schema()"
                    )
                )
            ).all()
        existing: dict[str, set[str]] = {}
        for table, column in columns:
            existing.setdefault(table, set()).add(column)
        missing = [
            f"{table}.{column}"
            for table, names in required.items()
            for column in sorted(names - existing.get(table, set()))
        ]
        if current != expected or missing:
            details = f"ревизия {current or 'нет'} (нужна {expected})"
            if missing:
                details += f"; отсутствуют поля: {', '.join(missing)}"
            raise RuntimeError(
                "Схема БД несовместима с кодом: "
                f"{details}. Выполните 'uv run python main.py migrate' перед запуском бота."
            )

    async def check_tables_exist(self):
        """Проверяет наличие основных таблиц"""
        if not self.engine:
            return False

        conn = await self.engine.connect()
        try:
            async with conn.begin():
                result = await conn.execute(
                    text(
                        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'users')"
                    )
                )
                users_exists = result.scalar()

                result = await conn.execute(
                    text(
                        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'subjects')"
                    )
                )
                subjects_exists = result.scalar()

                return users_exists and subjects_exists
        except Exception as e:
            logger.error(f"Ошибка проверки таблиц: {e}")
            return False
        finally:
            await conn.close()

    async def initialize(self, recreate_tables: bool = False):
        """Инициализация базы данных"""
        if not self.engine:
            await self.ensure_database_exists()
            await self.create_engine()

        if recreate_tables:
            await self.recreate_tables()
        else:
            await self.create_tables()

        self.initialized = True
        logger.info("БД инициализирована")

    async def create_tables(self):
        """Создание всех таблиц"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def recreate_tables(self):
        """Пересоздание всех таблиц с правильной структурой"""
        logger.warning("Пересоздание таблиц...")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    async def get_or_create_subject(
        self,
        name: str,
        year: int = None,
        start_module: int = None,
        end_module: int = None,
    ) -> Subject:
        """Получить или создать предмет"""
        async with self.async_session() as session:
            try:
                stmt = select(Subject).where(Subject.name == name)
                result = await session.execute(stmt)
                subject = result.scalar_one_or_none()

                if subject:
                    return subject

                subject = Subject(
                    name=name,
                    year=year,
                    start_module=start_module,
                    end_module=end_module,
                    is_active=True,
                )
                session.add(subject)
                await session.commit()
                await session.refresh(subject)
                return subject

            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка работы с предметом {name}: {e}")
                raise

    async def upsert_task(
        self, task_data: dict[str, Any]
    ) -> tuple[Task | None, dict[str, Any]]:
        """Создать или обновить дедлайн.
        Возвращает (deadline, change_info) где change_info содержит:
        - is_new: bool - является ли дедлайн новым
        - deadline_changed: bool - изменился ли soft или hard дедлайн
        - soft_deadline_changed: bool - изменился ли soft дедлайн
        - hard_deadline_changed: bool - изменился ли hard дедлайн
        - old_soft_deadline_ts: datetime | None - старое значение soft дедлайна
        - old_hard_deadline_ts: datetime | None - старое значение hard дедлайна"""
        async with self.async_session() as session:
            try:
                sheet_row_id = task_data.get("sheet_row_id")
                if not sheet_row_id:
                    return None, {
                        "is_new": False,
                        "deadline_changed": False,
                        "soft_deadline_changed": False,
                        "hard_deadline_changed": False,
                        "old_soft_deadline_ts": None,
                        "old_hard_deadline_ts": None,
                    }

                stmt = select(Task).where(Task.sheet_row_id == sheet_row_id)
                result = await session.execute(stmt)
                deadline = result.scalar_one_or_none()

                change_info = {
                    "is_new": False,
                    "deadline_changed": False,
                    "soft_deadline_changed": False,
                    "hard_deadline_changed": False,
                    "old_soft_deadline_ts": None,
                    "old_hard_deadline_ts": None,
                }

                if deadline:
                    # Сохраняем старые значения дедлайнов
                    old_soft = deadline.soft_deadline_ts
                    old_hard = deadline.hard_deadline_ts

                    # Проверяем изменения дедлайнов
                    new_soft = task_data.get("soft_deadline_ts")
                    new_hard = task_data.get("hard_deadline_ts")

                    soft_changed = old_soft != new_soft
                    hard_changed = old_hard != new_hard

                    if soft_changed or hard_changed:
                        change_info["deadline_changed"] = True
                        change_info["soft_deadline_changed"] = soft_changed
                        change_info["hard_deadline_changed"] = hard_changed
                        if soft_changed:
                            change_info["old_soft_deadline_ts"] = old_soft
                        if hard_changed:
                            change_info["old_hard_deadline_ts"] = old_hard

                    # Обновляем все поля (не только дедлайны)
                    fields_to_compare = [
                        "subject_id",
                        "hw_name",
                        "source_link",
                        "soft_deadline_ts",
                        "hard_deadline_ts",
                        "note",
                    ]

                    has_changes = False
                    for key in fields_to_compare:
                        if (
                            key in task_data
                            and getattr(deadline, key, None) != task_data[key]
                        ):
                            has_changes = True
                            setattr(deadline, key, task_data[key])

                    if has_changes:
                        deadline.updated_at = utc_now()
                else:
                    # Новый дедлайн
                    if "updated_at" not in task_data:
                        task_data["updated_at"] = utc_now()

                    deadline = Task(**task_data)
                    session.add(deadline)
                    change_info["is_new"] = True
                    # Для нового дедлайна считаем, что дедлайны "изменились" (чтобы отправить уведомление)
                    if deadline.soft_deadline_ts or deadline.hard_deadline_ts:
                        change_info["deadline_changed"] = True

                await session.commit()
                await session.refresh(deadline)
                return deadline, change_info

            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка работы с дедлайном {sheet_row_id}: {e}")
                raise

    async def get_all_subjects(self) -> list[Subject]:
        """Получить все предметы"""
        async with self.async_session() as session:
            stmt = select(Subject)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_subject_by_id(self, subject_id: int) -> Subject | None:
        """Получить предмет по ID"""
        async with self.async_session() as session:
            try:
                stmt = select(Subject).where(Subject.id == subject_id)
                result = await session.execute(stmt)
                return result.scalar_one_or_none()
            except Exception as e:
                logger.error(f"Ошибка получения предмета {subject_id}: {e}")
                return None

    async def delete_outdated_tasks(
        self, current_sheet_row_ids: list[int], source_sheet: str | None = None
    ):
        """Delete missing tasks from one successfully read sheet."""
        if not source_sheet:
            raise ValueError("source_sheet обязателен для безопасного удаления")
        async with self.async_session() as session:
            try:
                stmt = select(Task).where(
                    Task.source_sheet == source_sheet,
                    ~Task.sheet_row_id.in_(current_sheet_row_ids),
                )
                result = await session.execute(stmt)
                outdated_deadlines = result.scalars().all()

                if outdated_deadlines:
                    await session.execute(
                        delete(Task).where(
                            Task.id.in_(
                                [deadline.id for deadline in outdated_deadlines]
                            )
                        )
                    )
                    await session.commit()

                    logger.info(
                        f"Удалено {len(outdated_deadlines)} заданий листа {source_sheet}"
                    )

            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка удаления устаревших дедлайнов: {e}")
                raise

    async def get_user_by_id(self, tg_user_id: int) -> User:
        """Получить пользователя по ID"""
        async with self.async_session() as session:
            try:
                stmt = select(User).where(User.tg_user_id == tg_user_id)
                result = await session.execute(stmt)
                user = result.scalar_one_or_none()
                return user

            except Exception as e:
                logger.error(f"Ошибка получения пользователя {tg_user_id}: {e}")
                return None

    async def update_user_timezone(self, tg_user_id: int, timezone_name: str) -> bool:
        """Обновить часовой пояс пользователя"""
        async with self.async_session() as session:
            try:
                stmt = select(User).where(User.tg_user_id == tg_user_id)
                result = await session.execute(stmt)
                user = result.scalar_one_or_none()
                if not user:
                    return False
                changed = user.timezone != timezone_name
                user.timezone = timezone_name
                if changed:
                    session.add(
                        UserActionEvent(
                            user_id=tg_user_id,
                            event_name="settings_changed",
                            details={"setting": "timezone"},
                        )
                    )
                await session.commit()
                return True
            except Exception as e:
                await session.rollback()
                logger.error(
                    f"Ошибка обновления часового пояса пользователя {tg_user_id}: {e}"
                )
                return False

    async def create_user_notification_settings(
        self, user_id: int
    ) -> UserNotificationSettings:
        """Создать настройки уведомлений для пользователя"""
        settings = UserNotificationSettings(user_id=user_id)

        # Планируем уведомления для существующих подписок пользователя
        try:
            from src.bot.services.notification_scheduler_service import (
                notification_scheduler_service,
            )

            scheduled_count = await notification_scheduler_service.schedule_notifications_for_user_settings_creation(
                user_id
            )
            if scheduled_count > 0:
                logger.info(
                    f"При создании настроек уведомлений для пользователя {user_id} запланировано {scheduled_count} уведомлений"
                )
        except Exception as e:
            logger.error(
                f"Ошибка планирования уведомлений при создании настроек для пользователя {user_id}: {e}"
            )

        return settings

    async def get_user_notification_settings(
        self, user_id: int
    ) -> UserNotificationSettings:
        """Получить настройки уведомлений пользователя"""
        async with self.async_session() as session:
            try:
                await session.execute(
                    insert(UserNotificationSettings)
                    .values(user_id=user_id)
                    .on_conflict_do_nothing(constraint="unique_user_settings")
                )
                await session.commit()
                stmt = select(UserNotificationSettings).where(
                    UserNotificationSettings.user_id == user_id
                )
                result = await session.execute(stmt)
                return result.scalar_one()

            except Exception as e:
                logger.error(
                    f"Ошибка получения настроек уведомлений для пользователя {user_id}: {e}"
                )
                raise

    async def update_user_notification_settings(
        self,
        user_id: int,
        settings_data: dict,
        audit_details: dict[str, int | str | bool] | None = None,
    ) -> UserNotificationSettings:
        """Обновить настройки уведомлений пользователя"""
        async with self.async_session() as session:
            try:
                stmt = select(UserNotificationSettings).where(
                    UserNotificationSettings.user_id == user_id
                )
                result = await session.execute(stmt)
                settings = result.scalar_one_or_none()

                if not settings:
                    settings = await self.create_user_notification_settings(user_id)
                    session.add(settings)

                changed = False
                for key, value in settings_data.items():
                    if hasattr(settings, key):
                        changed = changed or getattr(settings, key) != value
                        setattr(settings, key, value)

                settings.last_modified = utc_now()

                if changed and audit_details is not None:
                    session.add(
                        UserActionEvent(
                            user_id=user_id,
                            event_name="settings_changed",
                            details=audit_details,
                        )
                    )

                await session.commit()
                await session.refresh(settings)
                return settings

            except Exception as e:
                await session.rollback()
                logger.error(
                    f"Ошибка обновления настроек уведомлений для пользователя {user_id}: {e}"
                )
                raise

    async def create_scheduled_notification(
        self, notification_data: dict
    ) -> ScheduledNotification:
        """Создать запланированное уведомление"""
        async with self.async_session() as session:
            try:
                notification = ScheduledNotification(**notification_data)
                session.add(notification)
                await session.commit()
                await session.refresh(notification)
                return notification

            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка создания запланированного уведомления: {e}")
                raise

    async def get_scheduled_notifications_for_delivery(
        self, time_window_minutes: int = 5, batch_size: int = 100
    ) -> list[ScheduledNotification]:
        """Atomically claim a delivery batch so concurrent workers cannot duplicate it."""
        async with self.async_session() as session:
            try:
                now = datetime.now(UTC)
                window_end = now + timedelta(minutes=time_window_minutes)
                stale_claim = now - timedelta(minutes=10)

                stmt = (
                    select(ScheduledNotification)
                    .join(User)
                    .join(Task, ScheduledNotification.deadline_id == Task.id)
                    .join(Subject, Task.subject_id == Subject.id)
                    .where(
                        and_(
                            User.is_active,
                            Task.is_archived.is_(False),
                            Subject.is_active,
                            Subject.is_archived.is_(False),
                            or_(
                                and_(
                                    ScheduledNotification.status == "scheduled",
                                    ScheduledNotification.planned_delivery_time
                                    <= window_end,
                                ),
                                and_(
                                    ScheduledNotification.status == "retry",
                                    or_(
                                        ScheduledNotification.next_attempt_at.is_(None),
                                        ScheduledNotification.next_attempt_at <= now,
                                    ),
                                ),
                                and_(
                                    ScheduledNotification.status == "processing",
                                    ScheduledNotification.claimed_at < stale_claim,
                                ),
                            ),
                        )
                    )
                    .order_by(ScheduledNotification.planned_delivery_time)
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )

                result = await session.execute(stmt)
                notifications = list(result.scalars().all())
                for notification in notifications:
                    notification.status = "processing"
                    notification.claimed_at = now
                    notification.attempt_count += 1
                await session.commit()
                return notifications

            except Exception as e:
                logger.error(f"Ошибка получения запланированных уведомлений: {e}")
                return []

    async def update_notification_status(
        self, notification_id: int, status: str, error_message: str = None
    ) -> bool:
        """Обновить статус уведомления"""
        async with self.async_session() as session:
            try:
                stmt = select(ScheduledNotification).where(
                    ScheduledNotification.id == notification_id
                )
                result = await session.execute(stmt)
                notification = result.scalar_one_or_none()

                if not notification:
                    return False

                if status == "failed":
                    status = "dead" if notification.attempt_count >= 5 else "retry"
                notification.status = status
                notification.last_error = error_message
                if status == "sent":
                    notification.sent_at = utc_now()
                    notification.next_attempt_at = None
                elif status == "retry":
                    delay_minutes = min(60, 2 ** max(notification.attempt_count - 1, 0))
                    notification.next_attempt_at = utc_now() + timedelta(
                        minutes=delay_minutes
                    )

                notification.updated_at = utc_now()

                await session.commit()
                return True

            except Exception as e:
                await session.rollback()
                logger.error(
                    f"Ошибка обновления статуса уведомления {notification_id}: {e}"
                )
                return False

    async def update_notification_statuses(
        self,
        notification_ids: list[int],
        status: str,
        error_message: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        if not notification_ids:
            return
        now = utc_now()
        values: dict[str, Any] = {
            "status": status,
            "updated_at": now,
            "last_error": error_message,
        }
        if status == "sent":
            values.update(sent_at=now, next_attempt_at=None)
        elif status == "retry":
            values["next_attempt_at"] = now + timedelta(
                seconds=retry_after_seconds or 60
            )
        async with self.async_session() as session:
            await session.execute(
                update(ScheduledNotification)
                .where(
                    ScheduledNotification.id.in_(notification_ids),
                    ScheduledNotification.status == "processing",
                )
                .values(**values)
            )
            await session.commit()

    async def cancel_scheduled_notifications_for_task(self, deadline_id: int) -> int:
        """Отменить все запланированные уведомления для задачи"""
        async with self.async_session() as session:
            try:
                stmt = select(ScheduledNotification).where(
                    and_(
                        ScheduledNotification.deadline_id == deadline_id,
                        ScheduledNotification.status.in_(
                            ["scheduled", "processing", "retry"]
                        ),
                    )
                )
                result = await session.execute(stmt)
                notifications = result.scalars().all()

                count = 0
                for notification in notifications:
                    notification.status = "cancelled"
                    notification.updated_at = utc_now()
                    count += 1

                await session.commit()
                return count

            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка отмены уведомлений для задачи {deadline_id}: {e}")
                return 0

    async def cleanup_old_notifications(self, days_old: int = 30) -> int:
        """Удалить старые отправленные уведомления"""
        async with self.async_session() as session:
            try:
                cutoff_date = utc_now() - timedelta(days=days_old)

                stmt = select(ScheduledNotification).where(
                    and_(
                        ScheduledNotification.status.in_(
                            ["sent", "failed", "cancelled"]
                        ),
                        ScheduledNotification.updated_at < cutoff_date,
                    )
                )
                result = await session.execute(stmt)
                old_notifications = result.scalars().all()

                count = len(old_notifications)
                for notification in old_notifications:
                    await session.delete(notification)

                await session.commit()
                return count

            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка очистки старых уведомлений: {e}")
                return 0

    async def close(self):
        """Закрыть соединение с базой данных"""
        if self.engine:
            await self.engine.dispose()


db_manager = DatabaseManager(auto_init=True)
