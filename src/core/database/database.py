
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select

from typing import Optional, List, Dict, Any
import os
from dotenv import load_dotenv
import asyncpg
import asyncio

from datetime import datetime
import pytz

from src.core.models import Base, Subject, Deadline, ALL_SUBJECTS
from src.utils import get_logger

load_dotenv('src/config/.env')
logger = get_logger()

class DatabaseManager:
    def __init__(self, auto_init: bool = False):
        self.database_url = os.getenv('DATABASE_URL')
        if not self.database_url:
            logger.critical("DATABASE_URL не найден в переменных окружения")
            raise ValueError("DATABASE_URL не найден в переменных окружения")
        
        # Извлекаем параметры подключения из URL
        self.db_host = os.getenv('DB_HOST', 'localhost')
        self.db_port = os.getenv('DB_PORT', '5432')
        self.db_name = os.getenv('DB_NAME', 'hse_bot_db')
        self.db_user = os.getenv('DB_USER', 'postgres')
        self.db_password = os.getenv('DB_PASSWORD', 'password')
        
        self.engine = None
        self.async_session = None
        self.auto_init = auto_init
        self.initialized = False
        logger.info("Менеджер базы данных инициализирован")

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
        
        # Проверяем наличие таблиц
        if not await self.check_tables_exist():
            logger.warning("Таблицы отсутствуют, восстанавливаем структуру БД...")
            await self.initialize(recreate_tables=True)
        elif not self.initialized:
            await self.initialize()
    
    async def check_tables_exist(self):
        """Проверяет наличие основных таблиц"""
        try:
            async with self.engine.begin() as conn:
                # Проверяем наличие таблицы users
                result = await conn.execute(
                    "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'users')"
                )
                users_exists = result.scalar()
                
                # Проверяем наличие таблицы subjects
                result = await conn.execute(
                    "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'subjects')"
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
    
    async def upsert_deadline(self, deadline_data: Dict[str, Any]) -> Optional[Deadline]:
        """Создать или обновить дедлайн"""
        async with self.async_session() as session:
            try:
                sheet_row_id = deadline_data.get('sheet_row_id')
                if not sheet_row_id:
                    return None
                
                stmt = select(Deadline).where(Deadline.sheet_row_id == sheet_row_id)
                result = await session.execute(stmt)
                deadline = result.scalar_one_or_none()
                
                if deadline:
                    # Проверяем изменения
                    has_changes = False
                    fields_to_compare = ['subject_id', 'hw_name', 'source_link', 'soft_deadline_ts', 'hard_deadline_ts', 'note']
                    
                    for key in fields_to_compare:
                        if key in deadline_data and getattr(deadline, key, None) != deadline_data[key]:
                            has_changes = True
                            setattr(deadline, key, deadline_data[key])
                    
                    if has_changes:
                        moscow_tz = pytz.timezone('Europe/Moscow')
                        deadline.last_updated = datetime.now(moscow_tz)
                else:
                    # Создаем новый дедлайн
                    if 'last_updated' not in deadline_data:
                        moscow_tz = pytz.timezone('Europe/Moscow')
                        deadline_data['last_updated'] = datetime.now(moscow_tz)
                    
                    deadline = Deadline(**deadline_data)
                    session.add(deadline)
                
                await session.commit()
                await session.refresh(deadline)
                return deadline
                
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
    
    async def get_all_deadlines(self) -> List[Deadline]:
        """Получить все дедлайны"""
        async with self.async_session() as session:
            stmt = select(Deadline)
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
    
    async def close(self):
        """Закрыть соединение с базой данных"""
        if self.engine:
            await self.engine.dispose()

db_manager = DatabaseManager(auto_init=True)