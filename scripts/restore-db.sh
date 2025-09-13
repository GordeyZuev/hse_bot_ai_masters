#!/bin/bash

# Скрипт для восстановления базы данных PostgreSQL HSE Bot из бэкапа
# Автор: Автоматически созданный скрипт
# Использование: ./restore-db.sh <путь_к_файлу_бэкапа>

set -e  # Остановить выполнение при любой ошибке

# Загружаем переменные окружения из .env файла
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
if [ -f "$PROJECT_DIR/src/config/.env" ]; then
    export $(grep -v '^#' "$PROJECT_DIR/src/config/.env" | xargs)
fi

# Конфигурация
CONTAINER_NAME="hse_bot_db"
LOG_FILE="$PROJECT_DIR/logs/restore.log"

# Создание директории для логов, если она не существует
mkdir -p "$(dirname "$LOG_FILE")"

# Функция для логирования
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

# Функция для показа справки
show_help() {
    cat << EOF
Использование: $0 <путь_к_файлу_бэкапа> [опции]

Опции:
    -h, --help          Показать эту справку
    -f, --force         Принудительное восстановление (без подтверждения)
    --drop-existing     Удалить существующую базу данных перед восстановлением

Примеры:
    $0 /path/to/backup.sql.gz
    $0 backups/hse_bot_db_backup_20240101_120000.sql.gz --force
    $0 backup.sql --drop-existing

EOF
}

# Функция для проверки существования контейнера
check_container() {
    if ! docker ps -q -f name="$CONTAINER_NAME" | grep -q .; then
        log "ОШИБКА: Контейнер $CONTAINER_NAME не запущен"
        exit 1
    fi
}

# Функция для получения переменных окружения из .env файла
load_env_vars() {
    local env_file="$PROJECT_DIR/src/config/.env"
    if [ -f "$env_file" ]; then
        # Экспортируем переменные из .env файла
        set -o allexport
        source "$env_file"
        set +o allexport
    fi
    
    # Установка значений по умолчанию, если переменные не заданы
    export POSTGRES_DB="${POSTGRES_DB:-hse_bot_db}"
    export POSTGRES_USER="${POSTGRES_USER:-postgres}"
    export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-password}"
}

# Функция для подтверждения действия
confirm_action() {
    if [ "$FORCE_MODE" = "true" ]; then
        return 0
    fi
    
    echo "⚠️  ВНИМАНИЕ: Это действие перезапишет текущую базу данных!"
    echo "База данных: $POSTGRES_DB"
    echo "Файл бэкапа: $BACKUP_FILE"
    echo ""
    read -p "Вы уверены, что хотите продолжить? (yes/no): " -r
    
    if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
        log "Восстановление отменено пользователем"
        exit 0
    fi
}

# Функция для подготовки файла бэкапа
prepare_backup_file() {
    local backup_file="$1"
    
    # Проверка существования файла
    if [ ! -f "$backup_file" ]; then
        log "ОШИБКА: Файл бэкапа не найден: $backup_file"
        exit 1
    fi
    
    # Если файл сжат, распаковываем его во временную директорию
    if [[ "$backup_file" == *.gz ]]; then
        local temp_file="/tmp/$(basename "$backup_file" .gz)"
        log "Распаковка сжатого бэкапа..."
        
        if gunzip -c "$backup_file" > "$temp_file"; then
            echo "$temp_file"
        else
            log "ОШИБКА: Не удалось распаковать файл бэкапа"
            exit 1
        fi
    else
        echo "$backup_file"
    fi
}

# Функция для удаления существующей базы данных
drop_database() {
    if [ "$DROP_EXISTING" = "true" ]; then
        log "Удаление существующей базы данных..."
        
        # Завершаем все активные соединения с базой данных
        docker exec "$CONTAINER_NAME" psql -U "$POSTGRES_USER" -d postgres -c \
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$POSTGRES_DB' AND pid <> pg_backend_pid();" || true
        
        # Удаляем базу данных
        docker exec "$CONTAINER_NAME" psql -U "$POSTGRES_USER" -d postgres -c \
            "DROP DATABASE IF EXISTS \"$POSTGRES_DB\";" || true
        
        # Создаем новую пустую базу данных
        docker exec "$CONTAINER_NAME" psql -U "$POSTGRES_USER" -d postgres -c \
            "CREATE DATABASE \"$POSTGRES_DB\";" || true
        
        log "База данных пересоздана"
    fi
}

# Функция для восстановления базы данных
restore_database() {
    local sql_file="$1"
    
    log "Начало восстановления базы данных из: $sql_file"
    
    # Восстанавливаем базу данных, передавая SQL через stdin
    if cat "$sql_file" | docker exec -i "$CONTAINER_NAME" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"; then
        log "База данных успешно восстановлена"
        
        # Если мы создавали временный файл, удаляем его
        if [[ "$sql_file" == /tmp/* ]]; then
            rm -f "$sql_file"
        fi
    else
        log "ОШИБКА: Не удалось восстановить базу данных"
        # Очистка
        if [[ "$sql_file" == /tmp/* ]]; then
            rm -f "$sql_file" || true
        fi
        exit 1
    fi
}

# Функция для проверки целостности восстановленной базы данных
verify_restore() {
    log "Проверка целостности восстановленной базы данных..."
    
    # Проверяем подключение к базе данных
    if docker exec "$CONTAINER_NAME" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT 1;" > /dev/null 2>&1; then
        log "✅ Подключение к базе данных успешно"
    else
        log "❌ Не удается подключиться к восстановленной базе данных"
        return 1
    fi
    
    # Проверяем наличие основных таблиц
    local table_count=$(docker exec "$CONTAINER_NAME" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c \
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';" | tr -d ' \n\r')
    
    if [ "$table_count" -gt 0 ]; then
        log "✅ Найдено $table_count таблиц в базе данных"
    else
        log "❌ Не найдено таблиц в восстановленной базе данных"
        return 1
    fi
    
    log "Проверка целостности завершена успешно"
    return 0
}

# Основная функция
main() {
    local backup_file="$1"
    
    log "=== Начало процесса восстановления ==="
    
    # Проверка аргументов
    if [ -z "$backup_file" ]; then
        log "ОШИБКА: Не указан файл бэкапа"
        show_help
        exit 1
    fi
    
    # Проверка зависимостей
    if ! command -v docker &> /dev/null; then
        log "ОШИБКА: Docker не установлен"
        exit 1
    fi
    
    # Загрузка переменных окружения
    load_env_vars
    
    # Проверка контейнера
    check_container
    
    # Подготовка файла бэкапа
    BACKUP_FILE="$backup_file"
    local sql_file=$(prepare_backup_file "$backup_file")
    
    # Подтверждение действия
    confirm_action
    
    # Удаление существующей базы данных (если требуется)
    drop_database
    
    # Восстановление базы данных
    restore_database "$sql_file"
    
    # Проверка целостности
    if verify_restore; then
        log "=== Восстановление завершено успешно ==="
    else
        log "=== Восстановление завершено с предупреждениями ==="
        exit 1
    fi
}

# Обработка аргументов командной строки
FORCE_MODE="false"
DROP_EXISTING="false"
BACKUP_FILE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        -f|--force)
            FORCE_MODE="true"
            shift
            ;;
        --drop-existing)
            DROP_EXISTING="true"
            shift
            ;;
        -*)
            log "ОШИБКА: Неизвестная опция $1"
            show_help
            exit 1
            ;;
        *)
            if [ -z "$BACKUP_FILE" ]; then
                BACKUP_FILE="$1"
            else
                log "ОШИБКА: Слишком много аргументов"
                show_help
                exit 1
            fi
            shift
            ;;
    esac
done

# Обработка сигналов
trap 'log "Получен сигнал прерывания, завершение работы..."; exit 1' INT TERM

# Запуск основной функции
main "$BACKUP_FILE"
