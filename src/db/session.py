"""
Конфигурация сессий базы данных.
"""
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
from src.utils.config import get_settings

settings = get_settings()

# Создаем асинхронный движок базы данных
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,  # Логирование SQL запросов в debug режиме
    poolclass=NullPool if settings.debug else None,  # Отключаем пул в debug режиме
    pool_pre_ping=True,  # Проверка соединения перед использованием
    pool_recycle=3600,  # Переподключение каждый час
)

# Создаем фабрику сессий
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=True,
    autocommit=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Генератор для получения сессии базы данных.
    Используется как dependency в FastAPI или для ручного управления сессиями.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_tables():
    """Создает все таблицы в базе данных."""
    from src.db.models import Base
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_tables():
    """Удаляет все таблицы из базы данных."""
    from src.db.models import Base
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def close_db():
    """Закрывает соединение с базой данных."""
    await engine.dispose()


class DatabaseManager:
    """Менеджер для работы с базой данных."""
    
    def __init__(self):
        self.engine = engine
        self.session_factory = AsyncSessionLocal
    
    async def get_session(self) -> AsyncSession:
        """Возвращает новую сессию базы данных."""
        return self.session_factory()
    
    async def health_check(self) -> bool:
        """Проверяет доступность базы данных."""
        try:
            from sqlalchemy import text
            async with self.session_factory() as session:
                await session.execute(text("SELECT 1"))
                return True
        except Exception:
            return False
    
    async def close(self):
        """Закрывает соединение с базой данных."""
        await self.engine.dispose()


# Глобальный экземпляр менеджера базы данных
db_manager = DatabaseManager()