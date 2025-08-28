#!/bin/bash

# Скрипт для запуска миграций базы данных
# Используется при развертывании приложения

set -e

echo "🔄 Запуск миграций базы данных..."

# Ожидание готовности базы данных
echo "⏳ Ожидание готовности PostgreSQL..."
while ! pg_isready -h ${DB_HOST:-db} -p ${DB_PORT:-5432} -U ${DB_USER:-postgres} -d ${DB_NAME:-hse_bot_db}; do
    echo "PostgreSQL недоступен - ожидание..."
    sleep 2
done

echo "✅ PostgreSQL готов!"

# Запуск миграций Alembic
echo "🔄 Применение миграций..."
alembic upgrade head

echo "✅ Миграции успешно применены!"

# Инициализация данных приложения (если нужно)
echo "🔄 Инициализация данных приложения..."
python -c "
import asyncio
import sys
sys.path.insert(0, '.')
from src.core.database import db_manager

async def init_data():
    await db_manager.ensure_initialized()
    print('✅ Данные приложения инициализированы!')

asyncio.run(init_data())
"

echo "🎉 Инициализация завершена успешно!"