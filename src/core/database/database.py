
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, text, and_
from typing import Optional, List, Dict, Any, Tuple
import os
from dotenv import load_dotenv
import asyncpg
import asyncio

from datetime import datetime, timedelta, timezone
import pytz
from src.utils.time import utc_now

from src.core.models import Base, Subject, Deadline, User, UserNotificationSettings, Subscription, ScheduledNotification, ALL_SUBJECTS
from src.utils import get_logger

# Загружаем переменные окружения
load_dotenv('src/config/.env')
logger = get_logger()

class DatabaseManager:
    def __init__(self, auto_init: bool = False):
        # Базовые параметры БД
        self.db_name = os.getenv('DB_NAME', os.getenv('POSTGRES_DB', 'hse_bot_db'))
        self.db_user = os.getenv('DB_USER', os.getenv('POSTGRES_USER', 'postgres'))
        self.db_password = os.getenv('DB_PASSWORD', os.getenv('POSTGRES_PASSWORD', 'password'))
        self.db_host = os.getenv('DB_HOST', 'localhost')
        self.db_port = os.getenv('DB_PORT', '5432')
        
        # Генерируем DATABASE_URL автоматически
        self.database_url = os.getenv('DATABASE_URL')
        if not self.database_url:
            self.database_url = f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
            # Логируем без пароля для безопасности
            safe_url = f"postgresql+asyncpg://{self.db_user}:***@{self.db_host}:{self.db_port}/{self.db_name}"
            logger.info(f"DATABASE_URL сгенерирован автоматически: {safe_url}")
        
        self.engine = None
        self.async_session = None
        self.auto_init = auto_init
        self.initialized = False
        logger.info(f"Менеджер базы данных инициализирован для БД: {self.db_name} на {self.db_host}:{self.db_port}")

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
                logger.info(f"Попытка подключения к PostgreSQL (попытка {attempt + 1}/{max_retries})")
                
                conn = await asyncpg.connect(
                    host=self.db_host,
                    port=int(self.db_port),
                    user=self.db_user,
                    password=self.db_password,
                    database='postgres',
                    timeout=10
                )
                
                result = await conn.fetchval(
                    "SELECT 1 FROM pg_database WHERE datname = $1",
                    self.db_name
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
                    logger.critical(f"Не удалось подключиться к PostgreSQL после {max_retries} попыток")
                    raise
                
                logger.info(f"Повторная попытка через {retry_delay} секунд...")
                await asyncio.sleep(retry_delay)

    async def create_engine(self):
        """Создает движок SQLAlchemy после того, как база данных существует"""
        self.engine = create_async_engine(
            self.database_url,
            echo=False,
            pool_pre_ping=True,
            pool_recycle=3600
        )
        
        self.async_session = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )

    async def ensure_initialized(self):
        """Гарантирует, что БД инициализирована"""
        if not self.engine:
            await self.ensure_database_exists()
            await self.create_engine()
        
        if not await self.check_tables_exist():
            logger.warning("Таблицы отсутствуют, восстанавливаем структуру БД...")
            await self.initialize(recreate_tables=True)
        elif not self.initialized:
            await self.initialize()
    
    async def check_tables_exist(self):
        """Проверяет наличие основных таблиц"""
        try:
            async with self.engine.begin() as conn:
                result = await conn.execute(
                    text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'users')")
                )
                users_exists = result.scalar()
                
                result = await conn.execute(
                    text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'subjects')")
                )
                subjects_exists = result.scalar()
                
                return users_exists and subjects_exists
        except Exception as e:
            logger.error(f"Ошибка проверки таблиц: {e}")
            return False

    async def initialize(self, recreate_tables: bool = False):
        """Инициализация базы данных"""
        if not self.engine:
            await self.ensure_database_exists()
            await self.create_engine()
        
        if recreate_tables:
            await self.recreate_tables()
        else:
            await self.create_tables()
        
        await self.populate_initial_subjects()
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
    
    async def get_or_create_subject(self, name: str, year: int = None, start_module: int = None, end_module: int = None) -> Subject:
        """Получить или создать предмет"""
        async with self.async_session() as session:
            try:
                stmt = select(Subject).where(Subject.name == name)
                result = await session.execute(stmt)
                subject = result.scalar_one_or_none()
                
                if subject:
                    return subject
                
                subject = Subject(name=name, year=year, start_module=start_module, end_module=end_module, is_active=True)
                session.add(subject)
                await session.commit()
                await session.refresh(subject)
                return subject
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка работы с предметом {name}: {e}")
                raise
    
    async def upsert_deadline(self, deadline_data: Dict[str, Any]) -> Tuple[Optional[Deadline], bool]:
        """Создать или обновить дедлайн. Возвращает (deadline, was_changed)."""
        async with self.async_session() as session:
            try:
                sheet_row_id = deadline_data.get('sheet_row_id')
                if not sheet_row_id:
                    return None, False
                
                stmt = select(Deadline).where(Deadline.sheet_row_id == sheet_row_id)
                result = await session.execute(stmt)
                deadline = result.scalar_one_or_none()
                
                was_changed = False
                if deadline:
                    has_changes = False
                    fields_to_compare = ['subject_id', 'hw_name', 'source_link', 'soft_deadline_ts', 'hard_deadline_ts', 'note']
                    
                    for key in fields_to_compare:
                        if key in deadline_data and getattr(deadline, key, None) != deadline_data[key]:
                            has_changes = True
                            setattr(deadline, key, deadline_data[key])
                    
                    if has_changes:
                        deadline.last_updated = utc_now()
                        was_changed = True
                else:
                    if 'last_updated' not in deadline_data:
                        deadline_data['last_updated'] = utc_now()
                    
                    deadline = Deadline(**deadline_data)
                    session.add(deadline)
                    was_changed = True
                
                await session.commit()
                await session.refresh(deadline)
                return deadline, was_changed
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка работы с дедлайном {sheet_row_id}: {e}")
                raise
    
    async def get_all_subjects(self) -> List[Subject]:
        """Получить все предметы"""
        async with self.async_session() as session:
            stmt = select(Subject)
            result = await session.execute(stmt)
            return list(result.scalars().all())
    
    
    async def delete_outdated_deadlines(self, current_sheet_row_ids: List[int]):
        """Удалить дедлайны, которых нет в текущих данных Google Sheets"""
        async with self.async_session() as session:
            try:
                stmt = select(Deadline).where(~Deadline.sheet_row_id.in_(current_sheet_row_ids))
                result = await session.execute(stmt)
                outdated_deadlines = result.scalars().all()
                
                if outdated_deadlines:
                    for deadline in outdated_deadlines:
                        await session.delete(deadline)
                    await session.commit()
                    logger.info(f"Удалено {len(outdated_deadlines)} устаревших дедлайнов")
                    
            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка удаления устаревших дедлайнов: {e}")
                raise
    
    async def populate_initial_subjects(self) -> bool:
        """Загрузить начальные дисциплины в базу данных"""
        try:
            existing_subjects = await self.get_all_subjects()
            if existing_subjects:
                return True
            
            loaded_count = 0
            for subject_data in ALL_SUBJECTS:
                try:
                    await self.get_or_create_subject(
                        name=subject_data["name"],
                        year=subject_data["year"],
                        start_module=subject_data["start_module"],
                        end_module=subject_data["end_module"]
                    )
                    loaded_count += 1
                except Exception as e:
                    logger.error(f"Ошибка загрузки дисциплины {subject_data['name']}: {e}")
                    continue
            
            logger.info(f"Загружено {loaded_count} дисциплин")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка загрузки дисциплин: {e}")
            return False
    
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
                user.timezone = timezone_name
                await session.commit()
                return True
            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка обновления часового пояса пользователя {tg_user_id}: {e}")
                return False

    async def create_user_notification_settings(self, user_id: int) -> UserNotificationSettings:
        """Создать настройки уведомлений для пользователя"""
        return UserNotificationSettings(user_id=user_id)

    async def get_user_notification_settings(self, user_id: int) -> UserNotificationSettings:
        """Получить настройки уведомлений пользователя"""
        async with self.async_session() as session:
            try:
                stmt = select(UserNotificationSettings).where(UserNotificationSettings.user_id == user_id)
                result = await session.execute(stmt)
                settings = result.scalar_one_or_none()
                
                if not settings:
                    settings = await self.create_user_notification_settings(user_id)
                    session.add(settings)
                    await session.commit()
                    await session.refresh(settings)
                
                return settings
                
            except Exception as e:
                logger.error(f"Ошибка получения настроек уведомлений для пользователя {user_id}: {e}")
                raise

    async def update_user_notification_settings(self, user_id: int, settings_data: dict) -> UserNotificationSettings:
        """Обновить настройки уведомлений пользователя"""
        async with self.async_session() as session:
            try:
                stmt = select(UserNotificationSettings).where(UserNotificationSettings.user_id == user_id)
                result = await session.execute(stmt)
                settings = result.scalar_one_or_none()
                
                if not settings:
                    settings = await self.create_user_notification_settings(user_id)
                    session.add(settings)
                
                for key, value in settings_data.items():
                    if hasattr(settings, key):
                        setattr(settings, key, value)
                
                settings.last_modified = utc_now()
                
                await session.commit()
                await session.refresh(settings)
                return settings
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка обновления настроек уведомлений для пользователя {user_id}: {e}")
                raise

    async def create_scheduled_notification(self, notification_data: dict) -> ScheduledNotification:
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

    async def get_scheduled_notifications_for_delivery(self, time_window_minutes: int = 5) -> List[ScheduledNotification]:
        """Получить уведомления для отправки в указанном временном окне.
        Включает как 'scheduled', так и 'failed' для повторной попытки доставки."""
        async with self.async_session() as session:
            try:
                now = datetime.now(timezone.utc)
                window_end = now + timedelta(minutes=time_window_minutes)
                
                stmt = select(ScheduledNotification).where(
                    and_(
                        ScheduledNotification.status.in_(['scheduled', 'failed']),
                        ScheduledNotification.planned_delivery_time <= window_end
                    )
                ).order_by(ScheduledNotification.planned_delivery_time)
                
                result = await session.execute(stmt)
                return list(result.scalars().all())
                
            except Exception as e:
                logger.error(f"Ошибка получения запланированных уведомлений: {e}")
                return []

    async def update_notification_status(self, notification_id: int, status: str, error_message: str = None) -> bool:
        """Обновить статус уведомления"""
        async with self.async_session() as session:
            try:
                stmt = select(ScheduledNotification).where(ScheduledNotification.id == notification_id)
                result = await session.execute(stmt)
                notification = result.scalar_one_or_none()
                
                if not notification:
                    return False
                
                notification.status = status
                if error_message:
                    pass
                
                notification.updated_at = utc_now()
                
                await session.commit()
                return True
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка обновления статуса уведомления {notification_id}: {e}")
                return False

    async def cancel_scheduled_notifications_for_deadline(self, deadline_id: int) -> int:
        """Отменить все запланированные уведомления для дедлайна"""
        async with self.async_session() as session:
            try:
                stmt = select(ScheduledNotification).where(
                    and_(
                        ScheduledNotification.deadline_id == deadline_id,
                        ScheduledNotification.status == 'scheduled'
                    )
                )
                result = await session.execute(stmt)
                notifications = result.scalars().all()
                
                count = 0
                for notification in notifications:
                    notification.status = 'cancelled'
                    notification.updated_at = utc_now()
                    count += 1
                
                await session.commit()
                return count
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка отмены уведомлений для дедлайна {deadline_id}: {e}")
                return 0

    async def cleanup_old_notifications(self, days_old: int = 30) -> int:
        """Удалить старые отправленные уведомления"""
        async with self.async_session() as session:
            try:
                cutoff_date = utc_now() - timedelta(days=days_old)
                
                stmt = select(ScheduledNotification).where(
                    and_(
                        ScheduledNotification.status.in_(['sent', 'failed', 'cancelled']),
                        ScheduledNotification.updated_at < cutoff_date
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