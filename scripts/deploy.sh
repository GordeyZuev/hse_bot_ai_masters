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

# Выдача прав пользователю на все существующие таблицы (если нужно)
echo "🔑 Выдача прав пользователю на существующие таблицы..."
docker exec -e PGPASSWORD="${POSTGRES_PASSWORD}" hse_bot_db psql -U postgres -d "${POSTGRES_DB:-hse_bot_db}" -c "
DO \$\$
DECLARE
    r RECORD;
BEGIN
    FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
        EXECUTE 'GRANT ALL ON TABLE public.' || quote_ident(r.tablename) || ' TO \"${POSTGRES_USER:-hse_bot_user}\"';
    END LOOP;
    
    FOR r IN (SELECT sequence_name FROM information_schema.sequences WHERE sequence_schema = 'public') LOOP
        EXECUTE 'GRANT ALL ON SEQUENCE public.' || quote_ident(r.sequence_name) || ' TO \"${POSTGRES_USER:-hse_bot_user}\"';
    END LOOP;
END \$\$;
" 2>/dev/null || echo "⚠️  Предупреждение: не удалось выдать права (возможно, пароль postgres отличается или права уже выданы)"

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