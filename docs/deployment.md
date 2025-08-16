# 🚀 Инструкция по развертыванию HSE Bot

Подробное руководство по развертыванию телеграм бота для уведомлений о дедлайнах.

## 📋 Предварительные требования

### Системные требования

- **ОС**: Ubuntu 20.04+ / CentOS 8+ / macOS 10.15+
- **RAM**: минимум 2GB, рекомендуется 4GB
- **CPU**: минимум 2 ядра
- **Диск**: минимум 10GB свободного места
- **Сеть**: стабильное интернет-соединение

### Программное обеспечение

- Python 3.11+
- PostgreSQL 13+
- Redis 6+
- Git
- Docker и Docker Compose (опционально)

## 🛠️ Способы развертывания

### 1. Развертывание с Docker (Рекомендуется)

#### Быстрое развертывание

```bash
# 1. Клонирование репозитория
git clone <repository-url>
cd hse_bot_ai_masters

# 2. Настройка конфигурации
cp config/.env.example config/.env
# Отредактируйте config/.env (см. раздел "Конфигурация")

# 3. Настройка Google Sheets API
# Поместите creds.json в config/creds.json

# 4. Запуск всех сервисов
docker-compose up -d

# 5. Проверка статуса
docker-compose ps
docker-compose logs -f bot
```

#### Продакшн развертывание

```bash
# 1. Создание продакшн конфигурации
cp docker-compose.yml docker-compose.prod.yml

# 2. Редактирование для продакшна
# - Убрать volume mapping для исходного кода
# - Добавить restart: always
# - Настроить ресурсы (memory, cpu limits)
# - Настроить сети и безопасность

# 3. Запуск в продакшн режиме
docker-compose -f docker-compose.prod.yml up -d

# 4. Настройка автозапуска
sudo systemctl enable docker
```

### 2. Ручное развертывание

#### Установка зависимостей (Ubuntu/Debian)

```bash
# Обновление системы
sudo apt update && sudo apt upgrade -y

# Установка Python 3.11
sudo apt install software-properties-common -y
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt update
sudo apt install python3.11 python3.11-venv python3.11-dev -y

# Установка PostgreSQL
sudo apt install postgresql postgresql-contrib -y
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Установка Redis
sudo apt install redis-server -y
sudo systemctl start redis-server
sudo systemctl enable redis-server

# Установка дополнительных пакетов
sudo apt install git curl build-essential -y
```

#### Настройка базы данных

```bash
# Создание пользователя и базы данных PostgreSQL
sudo -u postgres psql << EOF
CREATE USER hse_bot WITH PASSWORD 'secure_password_here';
CREATE DATABASE hse_bot_db OWNER hse_bot;
GRANT ALL PRIVILEGES ON DATABASE hse_bot_db TO hse_bot;
\q
EOF

# Настройка Redis (опционально)
sudo nano /etc/redis/redis.conf
# Раскомментируйте и настройте:
# requirepass your_redis_password_here
sudo systemctl restart redis-server
```

#### Развертывание приложения

```bash
# 1. Клонирование и настройка
git clone <repository-url>
cd hse_bot_ai_masters

# 2. Создание виртуального окружения
python3.11 -m venv .venv
source .venv/bin/activate

# 3. Установка зависимостей
pip install --upgrade pip
pip install -r requirements.txt

# 4. Настройка конфигурации
cp config/.env.example config/.env
nano config/.env  # Отредактируйте настройки

# 5. Применение миграций
alembic upgrade head

# 6. Тестовый запуск
python -m src.bot.main
```

## ⚙️ Конфигурация

### Основные настройки (.env)

```env
# Telegram Bot
BOT_TOKEN=1234567890:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
WEBHOOK_URL=  # Оставьте пустым для polling режима
WEBHOOK_PATH=/webhook

# Database
DATABASE_URL=postgresql+asyncpg://hse_bot:secure_password@localhost:5432/hse_bot_db
DB_HOST=localhost
DB_PORT=5432
DB_NAME=hse_bot_db
DB_USER=hse_bot
DB_PASSWORD=secure_password

# Redis
REDIS_URL=redis://localhost:6379/0
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# Google Sheets
GOOGLE_SHEETS_URL=https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit
GOOGLE_CREDS_FILE=config/creds.json

# Application
DEBUG=False
LOG_LEVEL=INFO
TIMEZONE=Europe/Moscow

# Performance
MAX_NOTIFICATIONS_PER_USER=2
DEFAULT_FIRST_NOTIFICATION_HOURS=24
DEFAULT_SECOND_NOTIFICATION_HOURS=2
NOTIFICATION_BATCH_SIZE=50
NOTIFICATION_RETRY_ATTEMPTS=3
TELEGRAM_RATE_LIMIT=25
```

### Настройка Google Sheets API

1. **Создание проекта в Google Cloud Console**:
   ```
   1. Перейдите на https://console.cloud.google.com/
   2. Создайте новый проект или выберите существующий
   3. Включите Google Sheets API и Google Drive API
   ```

2. **Создание Service Account**:
   ```
   1. Перейдите в IAM & Admin > Service Accounts
   2. Нажмите "Create Service Account"
   3. Заполните имя и описание
   4. Нажмите "Create and Continue"
   5. Пропустите роли (не обязательно)
   6. Нажмите "Done"
   ```

3. **Создание ключа**:
   ```
   1. Нажмите на созданный Service Account
   2. Перейдите на вкладку "Keys"
   3. Нажмите "Add Key" > "Create new key"
   4. Выберите JSON формат
   5. Скачайте файл и переименуйте в creds.json
   6. Поместите в config/creds.json
   ```

4. **Настройка доступа к таблице**:
   ```
   1. Откройте Google Sheets таблицу
   2. Нажмите "Share" (Поделиться)
   3. Добавьте email из Service Account (из creds.json)
   4. Дайте права "Viewer" или "Editor"
   ```

## 🔧 Настройка системных сервисов

### Systemd сервис (Linux)

Создайте файл `/etc/systemd/system/hse-bot.service`:

```ini
[Unit]
Description=HSE Bot AI Masters
After=network.target postgresql.service redis.service
Wants=postgresql.service redis.service

[Service]
Type=simple
User=hse-bot
Group=hse-bot
WorkingDirectory=/opt/hse_bot_ai_masters
Environment=PATH=/opt/hse_bot_ai_masters/.venv/bin
ExecStart=/opt/hse_bot_ai_masters/.venv/bin/python -m src.bot.main
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Ресурсы
MemoryMax=1G
CPUQuota=200%

# Безопасность
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/hse_bot_ai_masters/logs

[Install]
WantedBy=multi-user.target
```

Активация сервиса:

```bash
# Создание пользователя
sudo useradd -r -s /bin/false hse-bot
sudo chown -R hse-bot:hse-bot /opt/hse_bot_ai_masters

# Активация сервиса
sudo systemctl daemon-reload
sudo systemctl enable hse-bot.service
sudo systemctl start hse-bot.service

# Проверка статуса
sudo systemctl status hse-bot.service
sudo journalctl -u hse-bot.service -f
```

## 🔒 Безопасность

### Настройка файрвола

```bash
# UFW (Ubuntu)
sudo ufw enable
sudo ufw allow ssh
sudo ufw allow 5432/tcp  # PostgreSQL (только для внутренней сети)
sudo ufw allow 6379/tcp  # Redis (только для внутренней сети)
sudo ufw allow 8000/tcp  # Webhook (если используется)

# Или более строгие правила
sudo ufw allow from 10.0.0.0/8 to any port 5432
sudo ufw allow from 10.0.0.0/8 to any port 6379
```

### SSL/TLS для webhook

Если используете webhook режим:

```bash
# Установка Certbot
sudo apt install certbot -y

# Получение сертификата
sudo certbot certonly --standalone -d your-domain.com

# Настройка автообновления
sudo crontab -e
# Добавьте: 0 12 * * * /usr/bin/certbot renew --quiet
```

### Безопасность базы данных

```sql
-- Настройка PostgreSQL
-- В файле /etc/postgresql/13/main/postgresql.conf:
listen_addresses = 'localhost'
ssl = on

-- В файле /etc/postgresql/13/main/pg_hba.conf:
local   all             all                                     md5
host    all             all             127.0.0.1/32            md5
host    all             all             ::1/128                 md5
```

## 📊 Мониторинг

### Настройка логирования

```bash
# Ротация логов
sudo nano /etc/logrotate.d/hse-bot

# Содержимое файла:
/opt/hse_bot_ai_masters/logs/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 644 hse-bot hse-bot
    postrotate
        systemctl reload hse-bot.service
    endscript
}
```

### Мониторинг производительности

```bash
# Установка htop для мониторинга
sudo apt install htop -y

# Мониторинг в реальном времени
python scripts/performance_monitor.py monitor 3600 60

# Настройка cron для регулярных проверок
crontab -e
# Добавьте:
*/15 * * * * cd /opt/hse_bot_ai_masters && python scripts/performance_monitor.py >> logs/monitoring.log 2>&1
```

## 🔄 Обновление

### Обновление кода

```bash
# Остановка сервиса
sudo systemctl stop hse-bot.service

# Обновление кода
cd /opt/hse_bot_ai_masters
git pull origin main

# Обновление зависимостей
source .venv/bin/activate
pip install -r requirements.txt

# Применение миграций
alembic upgrade head

# Запуск сервиса
sudo systemctl start hse-bot.service
sudo systemctl status hse-bot.service
```

### Автоматическое обновление

Создайте скрипт `/opt/hse_bot_ai_masters/scripts/update.sh`:

```bash
#!/bin/bash
set -e

echo "Starting update process..."

# Остановка сервиса
sudo systemctl stop hse-bot.service

# Резервное копирование
cp -r /opt/hse_bot_ai_masters /opt/hse_bot_ai_masters.backup.$(date +%Y%m%d_%H%M%S)

# Обновление
cd /opt/hse_bot_ai_masters
git pull origin main

# Активация окружения и обновление зависимостей
source .venv/bin/activate
pip install -r requirements.txt

# Миграции
alembic upgrade head

# Запуск сервиса
sudo systemctl start hse-bot.service

# Проверка статуса
sleep 5
if sudo systemctl is-active --quiet hse-bot.service; then
    echo "Update completed successfully!"
else
    echo "Update failed! Check logs:"
    sudo journalctl -u hse-bot.service --no-pager -n 20
    exit 1
fi
```

## 🚨 Устранение неполадок

### Частые проблемы

1. **Бот не отвечает**:
   ```bash
   # Проверка статуса сервиса
   sudo systemctl status hse-bot.service
   
   # Просмотр логов
   sudo journalctl -u hse-bot.service -f
   
   # Проверка конфигурации
   python -c "from src.utils.config import settings; print(settings.bot_token[:10])"
   ```

2. **Ошибки базы данных**:
   ```bash
   # Проверка подключения к PostgreSQL
   psql -h localhost -U hse_bot -d hse_bot_db -c "SELECT 1;"
   
   # Проверка миграций
   alembic current
   alembic history
   ```

3. **Проблемы с Google Sheets**:
   ```bash
   # Тест подключения
   python -c "
   from src.bot.services.google_sheets import GoogleSheetsClient
   import asyncio
   
   async def test():
       client = GoogleSheetsClient('config/creds.json', 'YOUR_SHEET_URL')
       info = await client.get_sheet_info()
       print(info)
   
   asyncio.run(test())
   "
   ```

4. **Высокое использование памяти**:
   ```bash
   # Мониторинг памяти
   python scripts/performance_monitor.py
   
   # Перезапуск сервиса
   sudo systemctl restart hse-bot.service
   ```

### Диагностические команды

```bash
# Проверка всех сервисов
sudo systemctl status postgresql redis-server hse-bot.service

# Проверка портов
sudo netstat -tlnp | grep -E "(5432|6379|8000)"

# Проверка логов
tail -f /opt/hse_bot_ai_masters/logs/hse_bot_$(date +%Y%m%d).log

# Проверка производительности
python scripts/performance_monitor.py

# Тест базы данных
python -c "
import asyncio
from src.db import db_manager

async def test():
    healthy = await db_manager.health_check()
    print(f'Database healthy: {healthy}')

asyncio.run(test())
"
```

## 📞 Поддержка

При возникновении проблем:

1. Проверьте логи: `sudo journalctl -u hse-bot.service -f`
2. Запустите диагностику: `python scripts/performance_monitor.py`
3. Проверьте конфигурацию: `config/.env`
4. Убедитесь в доступности всех сервисов

Для получения помощи создайте issue с:
- Описанием проблемы
- Логами ошибок
- Конфигурацией (без секретных данных)
- Результатами диагностики