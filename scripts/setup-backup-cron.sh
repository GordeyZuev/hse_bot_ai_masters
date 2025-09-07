#!/bin/bash

# Скрипт для настройки cron задачи ежедневного бэкапа
# Автор: Автоматически созданный скрипт

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_SCRIPT="$SCRIPT_DIR/backup-db.sh"

# Функция для логирования
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1"
}

# Функция для показа справки
show_help() {
    cat << EOF
Использование: $0 [опции]

Опции:
    -h, --help          Показать эту справку
    -t, --time TIME     Время выполнения бэкапа (формат: HH:MM, по умолчанию: 02:00)
    --remove            Удалить cron задачу вместо добавления
    --show              Показать текущие cron задачи

Примеры:
    $0                  # Настроить бэкап на 02:00 каждый день
    $0 -t 03:30         # Настроить бэкап на 03:30 каждый день
    $0 --remove         # Удалить cron задачу бэкапа
    $0 --show           # Показать текущие cron задачи

EOF
}

# Функция для проверки формата времени
validate_time() {
    local time="$1"
    if [[ ! "$time" =~ ^([0-1][0-9]|2[0-3]):[0-5][0-9]$ ]]; then
        log "ОШИБКА: Неверный формат времени. Используйте HH:MM (например, 02:00)"
        exit 1
    fi
}

# Функция для добавления cron задачи
add_cron_job() {
    local backup_time="$1"
    local hour=$(echo "$backup_time" | cut -d: -f1)
    local minute=$(echo "$backup_time" | cut -d: -f2)
    
    # Удаляем ведущие нули для cron
    hour=$((10#$hour))
    minute=$((10#$minute))
    
    local cron_line="$minute $hour * * * $BACKUP_SCRIPT >> $PROJECT_DIR/logs/backup.log 2>&1"
    local cron_comment="# HSE Bot Database Backup - Ежедневный бэкап в $backup_time"
    
    log "Настройка cron задачи для ежедневного бэкапа в $backup_time"
    
    # Получаем текущий crontab
    local current_cron=$(crontab -l 2>/dev/null || echo "")
    
    # Проверяем, есть ли уже наша задача
    if echo "$current_cron" | grep -q "$BACKUP_SCRIPT"; then
        log "Cron задача уже существует, обновляем..."
        # Удаляем старую задачу
        current_cron=$(echo "$current_cron" | grep -v "$BACKUP_SCRIPT" | grep -v "HSE Bot Database Backup")
    fi
    
    # Добавляем новую задачу
    {
        echo "$current_cron"
        echo "$cron_comment"
        echo "$cron_line"
    } | crontab -
    
    log "✅ Cron задача успешно настроена"
    log "Бэкап будет выполняться каждый день в $backup_time"
    log "Логи сохраняются в: $PROJECT_DIR/logs/backup.log"
}

# Функция для удаления cron задачи
remove_cron_job() {
    log "Удаление cron задачи бэкапа..."
    
    local current_cron=$(crontab -l 2>/dev/null || echo "")
    
    if echo "$current_cron" | grep -q "$BACKUP_SCRIPT"; then
        # Удаляем задачи, связанные с нашим скриптом
        local new_cron=$(echo "$current_cron" | grep -v "$BACKUP_SCRIPT" | grep -v "HSE Bot Database Backup")
        echo "$new_cron" | crontab -
        log "✅ Cron задача успешно удалена"
    else
        log "Cron задача не найдена"
    fi
}

# Функция для показа текущих cron задач
show_cron_jobs() {
    log "Текущие cron задачи:"
    echo "=========================="
    crontab -l 2>/dev/null || echo "Нет настроенных cron задач"
    echo "=========================="
}

# Функция для проверки cron сервиса
check_cron_service() {
    # Проверяем, запущен ли cron сервис (для Linux)
    if command -v systemctl &> /dev/null; then
        if ! systemctl is-active --quiet cron 2>/dev/null && ! systemctl is-active --quiet crond 2>/dev/null; then
            log "ПРЕДУПРЕЖДЕНИЕ: Cron сервис может быть не запущен"
            log "Для запуска выполните: sudo systemctl start cron (или crond)"
        fi
    # Для macOS
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        if ! launchctl list | grep -q com.apple.cron; then
            log "ПРЕДУПРЕЖДЕНИЕ: Cron сервис может быть не запущен на macOS"
            log "Cron задачи могут не выполняться автоматически"
        fi
    fi
}

# Функция для проверки прав доступа
check_permissions() {
    if [ ! -x "$BACKUP_SCRIPT" ]; then
        log "ОШИБКА: Скрипт бэкапа не найден или не исполняемый: $BACKUP_SCRIPT"
        log "Убедитесь, что файл существует и имеет права на выполнение"
        exit 1
    fi
}

# Основная функция
main() {
    local action="add"
    local backup_time="02:00"
    
    # Обработка аргументов командной строки
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_help
                exit 0
                ;;
            -t|--time)
                backup_time="$2"
                validate_time "$backup_time"
                shift 2
                ;;
            --remove)
                action="remove"
                shift
                ;;
            --show)
                action="show"
                shift
                ;;
            -*)
                log "ОШИБКА: Неизвестная опция $1"
                show_help
                exit 1
                ;;
            *)
                log "ОШИБКА: Неожиданный аргумент $1"
                show_help
                exit 1
                ;;
        esac
    done
    
    log "=== Настройка cron задачи для бэкапа HSE Bot DB ==="
    
    # Проверки
    check_permissions
    check_cron_service
    
    # Выполнение действия
    case $action in
        add)
            add_cron_job "$backup_time"
            ;;
        remove)
            remove_cron_job
            ;;
        show)
            show_cron_jobs
            ;;
    esac
    
    log "=== Настройка завершена ==="
}

# Обработка сигналов
trap 'log "Получен сигнал прерывания, завершение работы..."; exit 1' INT TERM

# Запуск основной функции
main "$@"
