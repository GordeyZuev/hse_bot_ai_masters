# HSE AI Deadlines Bot

Телеграм-бот для уведомлений о дедлайнах магистратуры ВШЭ (направление «ИИ»). Интеграция с Google Sheets, персональные подписки и уведомления.

## 🚀 Что умеет
- Подписки на предметы и просмотр дедлайнов (только по подпискам)
- Персональные уведомления (за N дней/часов/минут; мягкие/жесткие дедлайны)
- Синхронизация с Google Sheets по расписанию и по требованию (админы)
- Админ-панель: статистика, рассылки, логи; быстрый запуск синхронизации

## 📦 Требования
- Python 3.11+
- Docker + Docker Compose (для продакшена — рекомендуется)
- Доступ к Google Sheets и файл `creds.json` Service Account

## ⚙️ Быстрый запуск (Docker)
1) Подготовьте файл `src/config/.env` (см. ниже) и `src/config/creds.json` (Google Service Account).  
2) Запуск:
```bash
docker-compose up -d --build
```
Полезно: `docker-compose logs -f app`, Adminer: http://localhost:8080

Замечания:
- Файл `src/config/creds.json` монтируется в контейнер (read-only). Проверьте путь.
- БД поднимается в контейнере `db`; данные сохраняются в volume `postgres_data`.

## 🚀 Развертывание на сервере

### Подготовка сервера
1. **Установка Docker и Docker Compose:**
```bash
# Ubuntu/Debian
sudo apt update
sudo apt install docker.io docker-compose-plugin
sudo systemctl enable docker
sudo usermod -aG docker $USER

# CentOS/RHEL
sudo yum install docker docker-compose-plugin
sudo systemctl enable docker
sudo usermod -aG docker $USER
```

2. **Клонирование репозитория:**
```bash
git clone <your-repo-url>
cd hse_bot_ai_masters
```

### Настройка окружения
1. **Создание файла конфигурации:**
```bash
cp src/config/.env.example src/config/.env
nano src/config/.env  # отредактируйте под ваши настройки
```

2. **Настройка Google Service Account:**
```bash
# Поместите файл creds.json в src/config/
chmod 600 src/config/creds.json
```

3. **Настройка прав доступа:**
```bash
chmod +x scripts/*.sh
```

### Развертывание
1. **Автоматическое развертывание (рекомендуется):**
```bash
./scripts/deploy.sh
```

2. **Ручное развертывание:**
```bash
# Остановка существующих контейнеров
docker-compose down

# Обновление кода (если используется git)
git pull

# Пересборка и запуск
docker-compose build --no-cache
docker-compose up -d

# Ожидание готовности БД
sleep 10

# Применение миграций
docker exec hse_bot_app python main.py migrate
```

### Проверка развертывания
```bash
# Статус контейнеров
docker-compose ps

# Логи приложения
docker-compose logs -f app

# Проверка подключения к БД
docker-compose exec db psql -U postgres -d hse_bot_db -c "SELECT 1;"

# Проверка работы бота
docker-compose logs app | grep "Bot started"
```

### Настройка автоматических бэкапов
```bash
# Настройка ежедневного бэкапа в 02:00
./scripts/setup-backup-cron.sh -t 02:00

# Проверка настроенных cron задач
./scripts/setup-backup-cron.sh --show
```

### Мониторинг и обслуживание
```bash
# Просмотр логов
docker-compose logs -f app

# Перезапуск приложения
docker-compose restart app

# Обновление приложения
./scripts/deploy.sh

# Создание бэкапа вручную
./scripts/backup-db.sh

# Восстановление из бэкапа
./scripts/restore-db.sh backups/hse_bot_db_backup_YYYYMMDD_HHMMSS.sql.gz
```

### Настройка для продакшена
1. **Настройка reverse proxy (nginx):**
```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    location /adminer {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

2. **Настройка SSL (Let's Encrypt):**
```bash
sudo apt install certbot nginx
sudo certbot --nginx -d your-domain.com
```

3. **Настройка firewall:**
```bash
sudo ufw allow 22    # SSH
sudo ufw allow 80    # HTTP
sudo ufw allow 443   # HTTPS
sudo ufw enable
```

### Переменные окружения для продакшена
```env
# Основные настройки
BOT_TOKEN=your_production_bot_token
ADMIN_IDS=123456789,987654321
TIMEZONE=Europe/Moscow
LOG_LEVEL=INFO

# База данных (автоматически настраивается в Docker)
DATABASE_URL=postgresql+asyncpg://postgres:secure_password@db:5432/hse_bot_db

# Google Sheets
GOOGLE_SHEETS_URL=https://docs.google.com/spreadsheets/d/your_sheet_id/edit
GOOGLE_CREDENTIALS_PATH=src/config/creds.json

# Планировщик
SYNC_INTERVAL_HOURS=1
NOTIFICATION_CHECK_MINUTES=5

# Уведомления (опционально)
TELEGRAM_BOT_TOKEN=your_bot_token_for_notifications
TELEGRAM_ADMIN_CHAT_ID=your_admin_chat_id

# Бэкапы
BACKUP_RETENTION_DAYS=7
```

## 🧩 Локальный запуск
```bash
pip install -r requirements.txt
python main.py         # полный режим: бот + синк + уведомления
```
Подрежимы: `python main.py bot | scheduler | sync`.

## 🔐 Конфигурация (`src/config/.env`)
Минимальный набор переменных:
```env
# Telegram
BOT_TOKEN=your_telegram_bot_token
ADMIN_IDS=123456789,987654321

# Database (локально)
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/hse_bot_db

# Google Sheets
GOOGLE_SHEETS_URL=https://docs.google.com/spreadsheets/d/your_sheet_id/edit
GOOGLE_CREDENTIALS_PATH=src/config/creds.json

# Time / Logging
TIMEZONE=Europe/Moscow
LOG_LEVEL=INFO
```
В Docker параметры БД берутся из `docker-compose.yml` и пробрасываются в `DATABASE_URL` автоматически.

Дополнительно (по необходимости):
```env
# Планировщик
SYNC_INTERVAL_HOURS=1           # частота синка
NOTIFICATION_CHECK_MINUTES=5    # частота проверки уведомлений

# Внешние ссылки (если используются в UI)
FCS_WIKI_URL=https://wiki.cs.hse.ru/
GOOGLE_SHEETS_LINK=https://docs.google.com/spreadsheets/d/your_sheet_id/edit
```

## 🗄️ Миграции БД
```bash
alembic upgrade head
```

## 🤖 Команды бота (основные)
- `/start`, `/help`
- `/deadlines [N]`
- `/sub`, `/unsub`, `/unsuball`, `/mysubs`
- `/admin` (только админы)

## 📚 Функциональность (подробно)

### Подписки на предметы
- Пользователь выбирает курс (1/2) и предметы для подписки.
- Команды:
  - `/sub` — мастер выбора предметов с инлайн‑кнопками.
  - `/mysubs` — показывает текущие подписки и быстрые действия (отписка).
  - `/unsub` — отписка от выбранного предмета.
  - `/unsuball` — мгновенная отписка от всех предметов.
- Хранение: таблица `subscriptions` (связь N:1 с `users` и `subjects`).

### Просмотр дедлайнов
- `/deadlines [N]` — вывод дедлайнов на N дней вперед.
- Показываются только дедлайны по подписанным предметам.
- Отображение:
  - Жесткие и мягкие дедлайны (soft/hard).
  - 24‑часовой формат времени в таймзоне `TIMEZONE`.
  - Оставшееся время «через X дн/ч/мин»; ссылка на задание (если есть).

### Уведомления о дедлайнах
- Настройка через `/settings` (инлайн‑UI):
  - До 2 персональных напоминаний на пользователя (например, «за 1 день», «за 2 часа»).
  - Типы интервалов: дни / часы / минуты до дедлайна.
  - Включение/выключение каждого уведомления.
- Отправка:
  - Планировщик проверяет окна напоминаний каждые `NOTIFICATION_CHECK_MINUTES` минут.
  - Учитывается тип дедлайна (soft/hard) и фактическое время `due_at`.
  - Дубликаты предотвращаются через статус/журнал уведомлений.
  - Для прошедших дедлайнов уведомления не ставятся.

### Админ‑панель
- Доступ: `/admin` (только ID из `ADMIN_IDS`).
- Разделы:
  - Статистика: пользователи, подписки, предстоящие дедлайны.
  - Синхронизация: ручной запуск синка с Google Sheets.
  - Рассылки: массовое сообщение всем пользователям (с подтверждением).
  - Логи: выдача текущих лог‑файлов.

### Синхронизация с Google Sheets
- Периодическая: каждые `SYNC_INTERVAL_HOURS` часов (через Scheduler).
- Ручная: из админ‑панели (быстрый синк).
- Процесс:
  1. `GSheetsSyncer` получает строки из `GOOGLE_SHEETS_URL`.
  2. `DataSyncer` нормализует и обновляет БД (`subjects`, `deadlines`).
  3. Удаление/архивация устаревших записей по правилам синка.

### Логирование
- Путь: `./logs/` (монтируется в Docker).
- Основные файлы: приложение/бот, синхронизация, уведомления.
- Ротация/архивирование — через конфиг логгера или внешние инструменты.

### Бэкапы БД
- Скрипты: `scripts/backup-db.sh`, `scripts/restore-db.sh`, `scripts/setup-backup-cron.sh`.
- Примеры:
```bash
# Настройка автоматического бэкапа
./scripts/setup-backup-cron.sh -t 02:00

# Создание бэкапа вручную
./scripts/backup-db.sh

# Восстановление из бэкапа
./scripts/restore-db.sh backups/hse_bot_db_backup_20240101_120000.sql.gz

# Восстановление с принудительным пересозданием БД
./scripts/restore-db.sh --force --drop-existing backups/latest.sql.gz
```

### Скрипты развертывания
- **`scripts/deploy.sh`** - автоматическое развертывание обновлений
- **`scripts/run-migrations.sh`** - выполнение миграций БД
- **`scripts/setup-backup-cron.sh`** - настройка автоматических бэкапов

Примеры использования:
```bash
# Полное развертывание с обновлением кода
./scripts/deploy.sh

# Только миграции БД
./scripts/run-migrations.sh

# Настройка бэкапа на 03:30
./scripts/setup-backup-cron.sh -t 03:30

# Просмотр настроенных cron задач
./scripts/setup-backup-cron.sh --show

# Удаление cron задач бэкапа
./scripts/setup-backup-cron.sh --remove
```

### Производительность и эксплуатация
- Режим «full» запускает бот+планировщик+уведомления вместе.
- Можно разносить процессы: `python main.py bot` и `python main.py scheduler`.
- Мониторинг: `docker-compose ps`, `docker-compose logs -f app`.

### Локализация и время
- Таймзона: `TIMEZONE` (например, `Europe/Moscow`).
- Время в 24‑часовом формате.

## 🧰 Траблшутинг

### Общие проблемы
- **Проверка creds:** `docker-compose exec app ls -la /app/src/config/creds.json`
- **Подключение к БД:** `docker-compose exec db psql -U postgres -d ${POSTGRES_DB:-hse_bot_db}`
- **Логи:** `./logs/` или `docker-compose logs -f app`

### Проблемы развертывания
1. **Контейнер не запускается:**
```bash
# Проверка логов
docker-compose logs app

# Проверка конфигурации
docker-compose config

# Пересборка без кэша
docker-compose build --no-cache
```

2. **Ошибки подключения к БД:**
```bash
# Проверка статуса БД
docker-compose exec db pg_isready -U postgres

# Проверка переменных окружения
docker-compose exec app env | grep DATABASE_URL

# Ручное подключение к БД
docker-compose exec db psql -U postgres -d hse_bot_db
```

3. **Проблемы с миграциями:**
```bash
# Проверка статуса миграций
docker-compose exec app alembic current

# Применение миграций вручную
docker-compose exec app alembic upgrade head

# Откат миграций (осторожно!)
docker-compose exec app alembic downgrade -1
```

4. **Проблемы с Google Sheets:**
```bash
# Проверка файла creds
docker-compose exec app ls -la /app/src/config/creds.json

# Тест подключения к Google Sheets
docker-compose exec app python -c "
from src.core.sync.gsheets_syncer import gsheets_syncer
import asyncio
asyncio.run(gsheets_syncer.test_connection())
"
```

5. **Проблемы с бэкапами:**
```bash
# Проверка прав доступа
ls -la scripts/backup-db.sh

# Ручной запуск бэкапа
./scripts/backup-db.sh

# Проверка cron задач
./scripts/setup-backup-cron.sh --show
```

### Мониторинг производительности
```bash
# Использование ресурсов контейнерами
docker stats

# Размер логов
du -sh logs/

# Размер бэкапов
du -sh backups/

# Количество записей в БД
docker-compose exec db psql -U postgres -d hse_bot_db -c "
SELECT 
    schemaname,
    tablename,
    n_tup_ins as inserts,
    n_tup_upd as updates,
    n_tup_del as deletes
FROM pg_stat_user_tables;
"
```

## 🛠 Разработка
- Быстрый синк из контейнера:
```bash
docker-compose exec app python -c "from src.core.sync.data_syncer import data_syncer; import asyncio; asyncio.run(data_syncer.sync_data())"
```
- Применение миграций в контейнере:
```bash
docker-compose exec app alembic upgrade head
```
- Перезапуск только приложения:
```bash
docker-compose restart app
```

---
Код и архитектура: см. `TECHNICAL.md`.