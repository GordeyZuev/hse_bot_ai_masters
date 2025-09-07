# 💾 Система бэкапов HSE Bot

## Быстрый старт

### 1. Настройка автоматического ежедневного бэкапа

```bash
# Настройка бэкапа на 02:00 каждый день
./scripts/setup-backup-cron.sh

# Или на определенное время (например, 03:30)
./scripts/setup-backup-cron.sh -t 03:30
```

### 2. Проверка настройки

```bash
# Показать текущие cron задачи
./scripts/setup-backup-cron.sh --show

# Проверить работу скрипта бэкапа вручную
./scripts/backup-db.sh
```

### 3. Восстановление из бэкапа (при необходимости)

```bash
# Показать доступные бэкапы
ls -la backups/

# Восстановить из бэкапа
./scripts/restore-db.sh backups/hse_bot_db_backup_20240101_120000.sql.gz
```

## Подробная документация

### Скрипты

#### `scripts/backup-db.sh`
- Создает бэкап PostgreSQL базы данных
- Автоматически сжимает бэкап с помощью gzip
- Выполняет ротацию старых бэкапов (по умолчанию 7 дней)
- Логирует все операции в `logs/backup.log`
- Проверяет целостность созданного бэкапа

#### `scripts/restore-db.sh`
- Восстанавливает базу данных из бэкапа
- Поддерживает сжатые (.gz) и обычные (.sql) файлы
- Имеет защиту от случайного запуска (требует подтверждения)
- Может полностью пересоздать базу данных

#### `scripts/setup-backup-cron.sh`
- Настраивает автоматический запуск бэкапа через cron
- Позволяет задать время выполнения
- Может удалить существующие cron задачи

### Параметры командной строки

#### backup-db.sh
```bash
./scripts/backup-db.sh
# Параметры берутся из переменных окружения
```

#### restore-db.sh
```bash
./scripts/restore-db.sh <путь_к_бэкапу> [опции]

Опции:
  -h, --help          Показать справку
  -f, --force         Восстановление без подтверждения
  --drop-existing     Удалить существующую БД перед восстановлением

Примеры:
  ./scripts/restore-db.sh backup.sql.gz
  ./scripts/restore-db.sh backup.sql --force --drop-existing
```

#### setup-backup-cron.sh
```bash
./scripts/setup-backup-cron.sh [опции]

Опции:
  -h, --help          Показать справку
  -t, --time TIME     Время выполнения (HH:MM, по умолчанию 02:00)
  --remove            Удалить cron задачу
  --show              Показать текущие cron задачи

Примеры:
  ./scripts/setup-backup-cron.sh              # Бэкап в 02:00
  ./scripts/setup-backup-cron.sh -t 03:30     # Бэкап в 03:30
  ./scripts/setup-backup-cron.sh --remove     # Удалить задачу
```

### Переменные окружения

Добавьте в файл `src/config/.env`:

```env
# Количество дней для хранения бэкапов (по умолчанию: 7)
BACKUP_RETENTION_DAYS=7

# Уведомления об ошибках (опционально)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_ADMIN_CHAT_ID=your_admin_chat_id
```

### Структура файлов

```
project/
├── backups/                                    # Директория бэкапов
│   ├── hse_bot_db_backup_20240101_020000.sql.gz
│   ├── hse_bot_db_backup_20240102_020000.sql.gz
│   └── ...
├── logs/
│   ├── backup.log                              # Логи бэкапов
│   └── restore.log                             # Логи восстановления
└── scripts/
    ├── backup-db.sh                            # Скрипт создания бэкапа
    ├── restore-db.sh                           # Скрипт восстановления
    └── setup-backup-cron.sh                   # Настройка cron
```

### Формат имен бэкапов

```
hse_bot_db_backup_YYYYMMDD_HHMMSS.sql.gz

Где:
- YYYY - год (4 цифры)
- MM - месяц (2 цифры)
- DD - день (2 цифры)
- HH - час (2 цифры, 24-часовой формат)
- MM - минуты (2 цифры)
- SS - секунды (2 цифры)

Пример: hse_bot_db_backup_20240315_143022.sql.gz
```

### Мониторинг

#### Проверка статуса cron задачи
```bash
# Показать активные cron задачи
crontab -l

# Проверить логи системы (Linux)
sudo journalctl -u cron

# Проверить логи бэкапов
tail -f logs/backup.log
```

#### Проверка размера бэкапов
```bash
# Показать размеры всех бэкапов
du -h backups/

# Показать последние 5 бэкапов
ls -lht backups/ | head -6
```

#### Тестирование восстановления
```bash
# Создать тестовый бэкап
./scripts/backup-db.sh

# Найти последний бэкап
LATEST_BACKUP=$(ls -t backups/ | head -1)

# Протестировать восстановление (с подтверждением)
./scripts/restore-db.sh "backups/$LATEST_BACKUP"
```

### Устранение неполадок

#### Проблема: Контейнер не найден
```
ОШИБКА: Контейнер hse_bot_db не запущен
```
**Решение:** Убедитесь, что Docker контейнер запущен:
```bash
docker ps | grep hse_bot_db
docker-compose up -d db
```

#### Проблема: Нет прав доступа
```
ОШИБКА: permission denied
```
**Решение:** Убедитесь, что скрипты исполняемые:
```bash
chmod +x scripts/*.sh
```

#### Проблема: Переменные окружения не загружаются
```
ОШИБКА: DATABASE_URL не найден
```
**Решение:** Проверьте файл `.env`:
```bash
ls -la src/config/.env
cat src/config/.env | grep DATABASE_URL
```

#### Проблема: Cron не работает
**Проверка:**
```bash
# Проверить статус cron сервиса (Linux)
sudo systemctl status cron

# Запустить cron сервис (Linux)
sudo systemctl start cron

# Проверить логи cron
sudo tail -f /var/log/cron
```

### Рекомендации по безопасности

1. **Регулярно проверяйте бэкапы** - тестируйте восстановление
2. **Мониторьте логи** - следите за ошибками в `logs/backup.log`
3. **Настройте уведомления** - используйте Telegram для получения уведомлений об ошибках
4. **Храните бэкапы в безопасном месте** - рассмотрите возможность копирования на удаленный сервер
5. **Документируйте процедуры** - ведите записи о восстановлениях

### Автоматизация

#### Скрипт для копирования бэкапов на удаленный сервер
```bash
#!/bin/bash
# Добавьте в cron для ежедневного копирования бэкапов
rsync -avz backups/ user@remote-server:/path/to/backup/storage/
```

#### Мониторинг через Telegram
Добавьте в `.env`:
```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_ADMIN_CHAT_ID=your_admin_chat_id
```

Скрипт автоматически отправит уведомление при ошибках бэкапа.

---

**Важно:** Всегда тестируйте процедуру восстановления в тестовой среде перед использованием в продакшене!
