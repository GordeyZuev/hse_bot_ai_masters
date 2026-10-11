#!/usr/bin/env bash

# Build, migrate and deploy a Compose installation in a controlled order.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

if ! docker compose version >/dev/null 2>&1; then
    echo "❌ Требуется Docker Compose plugin (команда 'docker compose')." >&2
    exit 1
fi
if [[ ! -f src/config/.env ]]; then
    echo "❌ Нужен src/config/.env." >&2
    exit 1
fi

compose=(docker compose --env-file src/config/.env)
no_cache=false
pull=false
migrate_only=false
for arg in "$@"; do
    case "$arg" in
        --no-cache|-n) no_cache=true ;;
        --pull) pull=true ;;
        --migrate-only) migrate_only=true ;;
        *) echo "Использование: $0 [--pull | --migrate-only] [--no-cache]" >&2; exit 2 ;;
    esac
done
if [[ "$pull" == true && "$migrate_only" == true ]]; then
    echo "❌ --pull и --migrate-only несовместимы." >&2
    exit 2
fi
if [[ "$migrate_only" != true && ! -f src/config/creds.json ]]; then
    echo "❌ Нужен src/config/creds.json для запуска приложения." >&2
    exit 1
fi

# Only the update command fetches code; deploy uses exactly the checked-out tree.
if [[ "$pull" == true ]]; then
    if [[ ! -d .git ]]; then
        echo "❌ Для обновления нужен Git checkout." >&2
        exit 1
    fi
    if [[ -n "$(git status --porcelain)" ]]; then
        echo "❌ Рабочее дерево не чистое. Сохраните или закоммитьте изменения перед make update." >&2
        exit 1
    fi
    echo "📥 Получение кода..."
    git pull --ff-only
fi

# Validate interpolation, required paths and service definitions from the
# checkout that is actually going to be deployed.
"${compose[@]}" config -q

# Avoid Docker creating a root-owned bind-mount directory on first deployment.
mkdir -p logs

if [[ "$migrate_only" == true ]]; then
    # A restarting/paused container can resume during a migration as well.
    for app_status in running restarting paused; do
        active_app="$("${compose[@]}" ps --status "$app_status" -q app)"
        if [[ -n "$active_app" ]]; then
            echo "❌ Приложение активно ($app_status). Для согласованного обновления используйте make deploy." >&2
            exit 1
        fi
    done
fi

echo "🔨 Сборка нового образа..."
if [[ "$no_cache" == true ]]; then
    "${compose[@]}" build --no-cache migrate
else
    "${compose[@]}" build migrate
fi

# Keep the old app alive until the new image and a database backup are ready.
"${compose[@]}" up -d --wait db
echo "🗃️ Резервная копия БД перед миграцией..."
"$SCRIPT_DIR/backup-db.sh"

if [[ "$migrate_only" == true ]]; then
    echo "🗄️ Миграции без запуска приложения..."
    "${compose[@]}" run --rm migrate
    echo "✅ Миграции выполнены. Приложение не запускалось."
    exit 0
fi

# Some migrations rename tables used by the old bot; avoid running old code
# against a new schema. Downtime starts only after the image and backup exist.
echo "⏸️ Остановка старого приложения перед миграцией..."
if [[ -n "$("${compose[@]}" ps -a -q app)" ]]; then
    "${compose[@]}" stop app
fi

echo "🗄️ Миграции..."
"${compose[@]}" run --rm migrate

echo "▶️ Обновление приложения..."
"${compose[@]}" up -d --no-deps app
"${compose[@]}" ps
echo "✅ Обновление завершено. Проверьте логи и работу бота в Telegram."
