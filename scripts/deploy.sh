#!/bin/bash

# Скрипт для развертывания обновлений на сервере

set -e

# Загружаем переменные окружения из .env файла
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
if [ -f "$PROJECT_DIR/src/config/.env" ]; then
    export $(grep -v '^#' "$PROJECT_DIR/src/config/.env" | xargs)
fi

echo "🚀 Начинаю развертывание обновлений..."

# Остановка контейнеров
echo "⏹️  Остановка контейнеров..."
if ! docker-compose down; then
    echo "❌ Ошибка при остановке контейнеров"
    exit 1
fi

# Обновление кода (если используется git)
if [ -d ".git" ]; then
    echo "📥 Обновление кода из репозитория..."
    if ! git pull; then
        echo "❌ Ошибка при обновлении кода"
        exit 1
    fi
fi

# Пересборка контейнеров
echo "🔨 Пересборка контейнеров..."
if ! docker-compose build --no-cache; then
    echo "❌ Ошибка при пересборке контейнеров"
    exit 1
fi

# Запуск контейнеров
echo "▶️  Запуск контейнеров..."
if ! docker-compose up -d; then
    echo "❌ Ошибка при запуске контейнеров"
    exit 1
fi

# Ожидание готовности базы данных
echo "⏳ Ожидание готовности базы данных..."
sleep 10

# Выполнение миграций
# ВАЖНО: Если миграции падают с ошибкой прав, выполните один раз:
# docker exec -i hse_bot_db psql -U postgres -d hse_bot_db < scripts/grant-privileges.sql

# Выполнение миграций
echo "🗄️  Выполнение миграций базы данных..."
if ! docker exec hse_bot_app uv run python main.py migrate; then
    echo "❌ Ошибка при выполнении миграций"
    exit 1
fi

# Проверка статуса
echo "✅ Проверка статуса контейнеров..."
docker-compose ps

echo "🎉 Развертывание завершено!"