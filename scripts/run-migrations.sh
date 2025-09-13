#!/bin/bash

# Скрипт для запуска миграций базы данных
# Используется при развертывании приложения

set -e

# Загружаем переменные окружения из .env файла
if [ -f "src/config/.env" ]; then
    export $(grep -v '^#' src/config/.env | xargs)
fi

echo "🔄 Запуск миграций базы данных..."

# Проверка наличия необходимых инструментов
if ! command -v pg_isready &> /dev/null; then
    echo "❌ pg_isready не найден. Установите postgresql-client"
    exit 1
fi

if ! command -v alembic &> /dev/null; then
    echo "❌ alembic не найден. Установите alembic"
    exit 1
fi

# Ожидание готовности базы данных
echo "⏳ Ожидание готовности PostgreSQL..."
while ! pg_isready -h ${DB_HOST:-db} -p ${DB_PORT:-5432} -U ${DB_USER:-postgres} -d ${DB_NAME:-hse_bot_db}; do
    echo "PostgreSQL недоступен - ожидание..."
    sleep 2
done

echo "✅ PostgreSQL готов!"

# Запуск миграций Alembic
echo "🔄 Применение миграций..."
if ! alembic upgrade head; then
    echo "❌ Ошибка при применении миграций"
    exit 1
fi

echo "✅ Миграции успешно применены!"

# Инициализация данных приложения (если нужно)
echo "🔄 Инициализация данных приложения..."
if ! python -c "
import asyncio
import sys
sys.path.insert(0, '.')
from src.core.database import db_manager

async def init_data():
    await db_manager.ensure_initialized()
    print('✅ Данные приложения инициализированы!')

asyncio.run(init_data())
"; then
    echo "❌ Ошибка при инициализации данных приложения"
    exit 1
fi

echo "🎉 Инициализация завершена успешно!"