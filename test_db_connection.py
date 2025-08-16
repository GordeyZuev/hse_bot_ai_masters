#!/usr/bin/env python3
"""
Скрипт для тестирования подключения к базе данных.
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

from src.utils.config import get_settings
from src.db.session import db_manager
from sqlalchemy.ext.asyncio import create_async_engine

async def test_connection():
    """Тестирует подключение к базе данных."""
    settings = get_settings()
    
    print("🔍 Тестирование подключения к базе данных...")
    print(f"📋 Настройки:")
    print(f"   DATABASE_URL: {settings.database_url}")
    print(f"   DB_HOST: {settings.db_host}")
    print(f"   DB_PORT: {settings.db_port}")
    print(f"   DB_NAME: {settings.db_name}")
    print(f"   DB_USER: {settings.db_user}")
    print(f"   DB_PASSWORD: {'*' * len(settings.db_password) if settings.db_password else 'None'}")
    print()
    
    # Тест 1: Прямое подключение через SQLAlchemy
    print("🧪 Тест 1: Прямое подключение через SQLAlchemy...")
    try:
        from sqlalchemy import text
        engine = create_async_engine(settings.database_url, echo=True)
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT 1 as test"))
            row = result.fetchone()
            print(f"✅ Прямое подключение успешно: {row}")
        await engine.dispose()
    except Exception as e:
        print(f"❌ Прямое подключение не удалось: {e}")
        print(f"   Тип ошибки: {type(e).__name__}")
    
    print()
    
    # Тест 2: Подключение через db_manager
    print("🧪 Тест 2: Подключение через db_manager...")
    try:
        health_ok = await db_manager.health_check()
        if health_ok:
            print("✅ db_manager.health_check() успешно")
        else:
            print("❌ db_manager.health_check() вернул False")
    except Exception as e:
        print(f"❌ db_manager.health_check() не удался: {e}")
        print(f"   Тип ошибки: {type(e).__name__}")
    
    print()
    
    # Тест 3: Подключение через сессию
    print("🧪 Тест 3: Подключение через сессию...")
    try:
        from sqlalchemy import text
        async with db_manager.session_factory() as session:
            result = await session.execute(text("SELECT current_user, current_database()"))
            row = result.fetchone()
            print(f"✅ Подключение через сессию успешно:")
            print(f"   Пользователь: {row[0]}")
            print(f"   База данных: {row[1]}")
    except Exception as e:
        print(f"❌ Подключение через сессию не удалось: {e}")
        print(f"   Тип ошибки: {type(e).__name__}")
    
    await db_manager.close()

if __name__ == "__main__":
    asyncio.run(test_connection())