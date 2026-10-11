#!/bin/bash

# Скрипт для бэкапа базы данных PostgreSQL HSE Bot
# Автор: Автоматически созданный скрипт
# Дата создания: $(date '+%Y-%m-%d %H:%M:%S')

set -e  # Остановить выполнение при любой ошибке

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Конфигурация
BACKUP_DIR="$PROJECT_DIR/backups"
CONTAINER_NAME="hse_bot_db"
LOG_FILE="$PROJECT_DIR/logs/backup.log"

# Создание директории для бэкапов, если она не существует
mkdir -p "$BACKUP_DIR"
mkdir -p "$(dirname "$LOG_FILE")"

# Функция для логирования
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE" >&2
}

# Функция для проверки существования контейнера
check_container() {
    if ! docker ps -q -f name="$CONTAINER_NAME" | grep -q .; then
        log "ОШИБКА: Контейнер $CONTAINER_NAME не запущен"
        exit 1
    fi
}

# Функция для создания бэкапа
create_backup() {
    local timestamp
    timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_filename="hse_bot_db_backup_${timestamp}.sql"
    local backup_path="$BACKUP_DIR/$backup_filename"
    
    log "Начало создания бэкапа: $backup_filename"
    
    # Создание бэкапа с помощью pg_dump внутри контейнера
    if docker exec "$CONTAINER_NAME" sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "$backup_path"; then
        log "Бэкап успешно создан: $backup_path"
        
        # Сжатие бэкапа
        if gzip "$backup_path"; then
            log "Бэкап сжат: ${backup_path}.gz"
            echo "${backup_path}.gz"
        else
            log "ПРЕДУПРЕЖДЕНИЕ: Не удалось сжать бэкап"
            echo "$backup_path"
        fi
    else
        log "ОШИБКА: Не удалось создать бэкап"
        exit 1
    fi
}

# Функция для ротации старых бэкапов
rotate_backups() {
    local retention_days=${BACKUP_RETENTION_DAYS:-7}  # По умолчанию хранить 7 дней
    
    log "Начало ротации бэкапов (хранить последние $retention_days дней)"
    
    # Удаление бэкапов старше retention_days дней
    find "$BACKUP_DIR" -name "hse_bot_db_backup_*.sql.gz" -type f -mtime +"$retention_days" -delete 2>/dev/null || true
    find "$BACKUP_DIR" -name "hse_bot_db_backup_*.sql" -type f -mtime +"$retention_days" -delete 2>/dev/null || true
    
    # Подсчет количества оставшихся бэкапов
    local backup_count
    backup_count=$(find "$BACKUP_DIR" -name "hse_bot_db_backup_*" -type f | wc -l)
    log "Ротация завершена. Осталось бэкапов: $backup_count"
}

# Функция для проверки размера бэкапа
check_backup_size() {
    local backup_file="$1"
    local min_size_bytes=1  # Пустая новая БД тоже даёт маленький, но валидный дамп.
    
    if [ -f "$backup_file" ]; then
        local file_size
        file_size=$(wc -c < "$backup_file" 2>/dev/null || echo "0")
        if [ "$file_size" -lt "$min_size_bytes" ]; then
            log "ПРЕДУПРЕЖДЕНИЕ: Размер бэкапа подозрительно мал ($file_size байт)"
            return 1
        fi
        if [[ "$backup_file" == *.gz ]] && ! gzip -t "$backup_file"; then
            log "ОШИБКА: Сжатый бэкап повреждён"
            return 1
        fi
        log "Размер бэкапа: $file_size байт"
    else
        log "ОШИБКА: Файл бэкапа не найден: $backup_file"
        return 1
    fi
    return 0
}

# Функция для отправки уведомления об ошибке (опционально)
send_notification() {
    local message="$1"
    local status="$2"  # success или error
    
    # Здесь можно добавить отправку уведомлений через Telegram, email и т.д.
    # Например, через curl к API Telegram бота
    if [ "$status" = "error" ] && [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_ADMIN_CHAT_ID" ]; then
        curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
            -d "chat_id=$TELEGRAM_ADMIN_CHAT_ID" \
            -d "text=🚨 Ошибка бэкапа БД HSE Bot: $message" >/dev/null 2>&1 || true
    elif [ "$status" = "success" ] && [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_ADMIN_CHAT_ID" ]; then
        curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
            -d "chat_id=$TELEGRAM_ADMIN_CHAT_ID" \
            -d "text=✅ Бэкап БД HSE Bot: $message" >/dev/null 2>&1 || true
    fi
}

# Основная функция
main() {
    log "=== Начало процесса бэкапа ==="
    
    # Проверка зависимостей
    if ! command -v docker &> /dev/null; then
        log "ОШИБКА: Docker не установлен"
        send_notification "Docker не установлен" "error"
        exit 1
    fi
    
    # Проверка контейнера
    check_container
    
    # Создание бэкапа
    backup_file=$(create_backup)
    
    # Проверка размера бэкапа
    if check_backup_size "$backup_file"; then
        log "Бэкап прошел проверку качества"
        
        # Ротация старых бэкапов
        rotate_backups
        
        log "=== Процесс бэкапа завершен успешно ==="
        send_notification "Бэкап базы данных создан успешно" "success"
    else
        log "ОШИБКА: Бэкап не прошел проверку качества"
        send_notification "Бэкап не прошел проверку качества" "error"
        exit 1
    fi
}

# Обработка сигналов
trap 'log "Получен сигнал прерывания, завершение работы..."; exit 1' INT TERM

# Запуск основной функции
main "$@"
