# 🚀 Руководство по развертыванию HSE AI Deadlines Bot

> Подробное руководство по развертыванию и настройке бота в различных средах

**📖 [← Вернуться к основной документации](../README.md)**

## 📋 Содержание

- [Быстрый старт](#-быстрый-старт)
- [Подготовка сервера](#-подготовка-сервера)
- [Настройка окружения](#-настройка-окружения)
- [Режимы работы](#-режимы-работы)
- [Развертывание](#-развертывание)
- [Проверка работы](#-проверка-работы)
- [Мониторинг и обслуживание](#-мониторинг-и-обслуживание)
- [Настройка для продакшена](#-настройка-для-продакшена)
- [Резервное копирование](#-резервное-копирование)
- [Устранение неполадок](#-устранение-неполадок)

## ⚡ Быстрый старт

> **Важно:** Перед началом убедитесь, что Docker, `make`, `uv` и `git` установлены. Если нет, перейдите к разделу "[Подготовка сервера](#-подготовка-сервера)" ниже.

### 🐳 Docker (рекомендуется для продакшена)

1. **Клонируйте репозиторий:**
```bash
git clone <your-repo-url>
cd hse_bot_ai_masters
```

2. **Настройте конфигурацию:**
```bash
cp src/config/.env.example src/config/.env
nano src/config/.env  # отредактируйте под ваши настройки
```

3. **Добавьте Google Service Account:**
```bash
# Поместите файл creds.json в src/config/
chmod 600 src/config/creds.json
```

4. **Установите зависимости:**
```bash
# Полная настройка (установка uv + зависимости)
make setup

# Или только зависимости (если uv уже установлен)
make install
```

5. **Запустите:**
```bash
# С помощью Makefile (рекомендуется)
make run

# Или напрямую
docker-compose up -d --build
```

6. **Проверьте работу:**
```bash
# С помощью Makefile
make logs

# Или напрямую
docker-compose logs -f app
```

### 🐍 Локальный запуск (для разработки)

> **Примечание:** Для продакшена рекомендуется использовать Docker.

1. **Клонируйте репозиторий:**
```bash
git clone <your-repo-url>
cd hse_bot_ai_masters
```

2. **Установите зависимости:**
```bash
# Полная настройка (установка uv + зависимости)
make setup

# Или только зависимости (если uv уже установлен)
make install
```

3. **Настройте PostgreSQL (локально):**
```bash
# Создайте базу данных
createdb hse_bot_db
```

4. **Настройте конфигурацию:**
```bash
cp src/config/.env.example src/config/.env
# Отредактируйте .env файл
```

5. **Запустите:**
```bash
# С помощью Makefile (рекомендуется)
make run

# Или напрямую через uv
uv run python main.py full
```

## 🖥️ Подготовка сервера

### 🐧 Ubuntu/Debian

```bash
# Обновление системы
sudo apt update && sudo apt upgrade -y

# Установка Docker
sudo apt install -y apt-transport-https ca-certificates curl gnupg lsb-release
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Настройка пользователя
sudo usermod -aG docker $USER
sudo systemctl enable docker
sudo systemctl start docker

# Установка дополнительных инструментов
sudo apt install -y git nano htop curl wget make
```

### 🔴 CentOS/RHEL

```bash
# Обновление системы
sudo yum update -y

# Установка Docker
sudo yum install -y yum-utils
sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo yum install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Настройка пользователя
sudo usermod -aG docker $USER
sudo systemctl enable docker
sudo systemctl start docker

# Установка дополнительных инструментов
sudo yum install -y git nano htop curl wget make
```

### 🍎 macOS

```bash
# Установка Homebrew (если не установлен)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Установка Docker Desktop
brew install --cask docker

# Установка дополнительных инструментов
brew install git nano htop curl wget make uv
```

## ⚙️ Настройка окружения

> **Примечание:** Если вы следовали инструкциям по подготовке сервера выше, `uv` и `make` уже установлены. Если нет, воспользуйтесь командами ниже.

### 🚀 Проверка установки

Убедитесь, что все инструменты установлены:

```bash
# Проверка Docker
docker --version

# Проверка docker-compose
docker-compose --version

# Проверка uv
uv --version

# Проверка make
make --version

# Проверка git
git --version
```

Если что-то не установлено, вернитесь к разделу "Подготовка сервера" выше.

### 🔧 Управление проектом с Makefile

Makefile упрощает выполнение основных команд проекта:

#### Основные команды

```bash
make help           # Показать все доступные команды

# Установка
make install-uv     # Установить uv менеджер пакетов
make setup          # Полная установка (uv + зависимости)
make install        # Установить зависимости
make install-dev    # Установить зависимости для разработки

# Запуск
make run            # Запустить бота с синхронизацией и уведомлениями
make logs           # Просмотреть логи за сегодня

# Проверка кода
make lint           # Проверить код с помощью ruff
make lint-fix       # Автоматически исправить проблемы с кодом
make format         # Отформатировать код

# Обслуживание
make clean          # Очистить временные файлы
make update         # Обновить проект (остановить, git pull, перезапустить)
make clean-docker   # Очистить неиспользуемые Docker образы и контейнеры
make db             # Подключиться к базе данных PostgreSQL
```

### 📦 Управление зависимостями с uv

#### Основные команды

```bash
# Синхронизация зависимостей (установка всех пакетов из pyproject.toml)
uv sync

# Установка зависимостей для разработки
uv sync --dev

# Добавление новой зависимости
uv add package-name

# Добавление dev зависимости
uv add --dev package-name

# Удаление зависимости
uv remove package-name

# Обновление зависимостей
uv lock --upgrade

# Запуск команд в виртуальном окружении
uv run python main.py full
uv run alembic upgrade head

# Проверка качества кода
uv run ruff check .            # проверка кода
uv run ruff check --fix .      # автоисправление
uv run ruff format .           # форматирование
```

#### Преимущества uv

- **Скорость**: В 10-100 раз быстрее pip
- **Надежность**: Детерминированные сборки с lock-файлом
- **Совместимость**: Полная совместимость с pip и PyPI
- **Простота**: Один инструмент для всех задач Python
- **Безопасность**: Автоматическое управление виртуальными окружениями

### 🔍 Проверка качества кода с ruff

`ruff` - это современный и быстрый линтер и форматтер для Python, который заменяет несколько инструментов сразу.

#### Основные команды

```bash
# Проверка кода
uv run ruff check .            # проверка кода
uv run ruff check --fix .      # автоисправление проблем
uv run ruff format .           # форматирование кода

# Использование скриптов
./scripts/lint.sh              # полная проверка качества кода
./scripts/fix-code.sh          # автоисправление и форматирование
```

#### Преимущества ruff

- **Скорость**: В 10-100 раз быстрее black, isort, flake8
- **Все в одном**: Заменяет black, isort, flake8, pyupgrade
- **Автоисправление**: Может исправлять большинство проблем автоматически
- **Совместимость**: Полная совместимость с существующими инструментами
- **Настраиваемость**: Гибкая конфигурация через pyproject.toml

### 📁 Структура проекта

```
hse_bot_ai_masters/
├── src/
│   ├── config/
│   │   ├── .env              # Конфигурация (создать)
│   │   └── creds.json        # Google Service Account (добавить)
│   ├── bot/                  # Код бота
│   ├── core/                 # Основная логика
│   └── utils/                # Утилиты
├── scripts/                  # Скрипты развертывания
├── logs/                     # Логи (создается автоматически)
├── backups/                  # Бэкапы (создается автоматически)
├── docker-compose.yml        # Docker конфигурация
├── pyproject.toml            # Конфигурация проекта и зависимости (uv)
├── uv.lock                   # Lock-файл зависимостей (создается автоматически)
├── Makefile                  # Команды для управления проектом
├── requirements.txt          # Python зависимости (legacy, для совместимости)
└── README.md                 # Основная документация
```

### 🔐 Конфигурация (.env)

Создайте файл `src/config/.env`:

```env
# ===========================================
# ОСНОВНЫЕ НАСТРОЙКИ
# ===========================================

# Telegram Bot Token (получить у @BotFather)
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz

# ID администраторов (через запятую)
ADMIN_IDS=123456789,987654321

# Часовой пояс
TIMEZONE=Europe/Moscow

# Уровень логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL)
LOG_LEVEL=INFO

# ===========================================
# БАЗА ДАННЫХ
# ===========================================

# URL подключения к PostgreSQL
# Для Docker (автоматически):
DATABASE_URL=postgresql+asyncpg://postgres:secure_password@db:5432/hse_bot_db

# Для локального запуска:
# DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/hse_bot_db

# ===========================================
# GOOGLE SHEETS
# ===========================================

# URL Google Sheets с данными о дедлайнах
GOOGLE_SHEETS_URL=https://docs.google.com/spreadsheets/d/your_sheet_id/edit

# Путь к файлу Service Account (относительно src/config/)
GOOGLE_CREDENTIALS_PATH=src/config/creds.json

# ===========================================
# ПЛАНИРОВЩИК
# ===========================================

# Интервал синхронизации (часы)
SYNC_INTERVAL_HOURS=1

# Интервал проверки уведомлений (минуты)
NOTIFICATION_CHECK_MINUTES=15  # отправка по кратным 15 минутам (UTC)

# ===========================================
# ДОПОЛНИТЕЛЬНЫЕ НАСТРОЙКИ
# ===========================================

# Размер батча для уведомлений
NOTIFICATION_BATCH_SIZE=50

# Количество попыток отправки
NOTIFICATION_RETRY_ATTEMPTS=3

# Размер пула соединений с БД
DB_POOL_SIZE=10

# Максимальное переполнение пула
DB_MAX_OVERFLOW=20

# ===========================================
# ВНЕШНИЕ ССЫЛКИ (опционально)
# ===========================================

# Ссылка на Wiki ФКН
FCS_WIKI_URL=https://wiki.cs.hse.ru/

# Прямая ссылка на Google Sheets
GOOGLE_SHEETS_LINK=https://docs.google.com/spreadsheets/d/your_sheet_id/edit
```

### 🔑 Google Service Account

1. **Создайте проект в Google Cloud Console:**
   - Перейдите в [Google Cloud Console](https://console.cloud.google.com/)
   - Создайте новый проект или выберите существующий

2. **Включите Google Sheets API:**
   - В разделе "APIs & Services" → "Library"
   - Найдите "Google Sheets API" и включите его

3. **Создайте Service Account:**
   - Перейдите в "APIs & Services" → "Credentials"
   - Нажмите "Create Credentials" → "Service Account"
   - Заполните данные и создайте аккаунт

4. **Скачайте ключ:**
   - Нажмите на созданный Service Account
   - Перейдите в "Keys" → "Add Key" → "Create new key"
   - Выберите "JSON" и скачайте файл

5. **Настройте доступ к Google Sheets:**
   - Откройте ваш Google Sheets документ
   - Нажмите "Share" и добавьте email Service Account
   - Дайте права "Editor" или "Viewer" (в зависимости от потребностей)

6. **Поместите файл в проект:**
```bash
# Переименуйте скачанный файл в creds.json
mv ~/Downloads/your-service-account-key.json src/config/creds.json

# Установите правильные права доступа
chmod 600 src/config/creds.json
```

### 🗄️ Настройка PostgreSQL (для локального запуска)

```bash
# Установка PostgreSQL
sudo apt install postgresql postgresql-contrib  # Ubuntu/Debian
sudo yum install postgresql-server postgresql-contrib  # CentOS/RHEL

# Запуск службы
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Создание пользователя и базы данных
sudo -u postgres psql
```

```sql
-- В psql:
CREATE USER hse_bot_user WITH PASSWORD 'secure_password';
CREATE DATABASE hse_bot_db OWNER hse_bot_user;
GRANT ALL PRIVILEGES ON DATABASE hse_bot_db TO hse_bot_user;
\q
```

## 🚀 Режимы работы

### 🎯 **Полный режим** (рекомендуется)
Через Makefile:
```bash
make run
```

Или напрямую:
```bash
uv run python main.py full
```
- Бот + синхронизация + уведомления
- Автоматическое планирование задач
- Полный функционал системы

### 🤖 **Только бот**
```bash
uv run python main.py bot
```
- Только интерфейс пользователя
- Без автоматической синхронизации
- Без уведомлений

### 🔄 **Только синхронизация**
```bash
uv run python main.py scheduler
```
- Планировщик синхронизации
- Без интерфейса бота
- Для серверных задач

### ⚡ **Одиночная синхронизация**
```bash
uv run python main.py sync
```
- Выполнить синхронизацию один раз
- Полезно для тестирования
- Завершение после выполнения

### 🗄️ **Управление БД**
```bash
uv run python main.py migrate    # Применить миграции (если нужно)
uv run python main.py restore    # Восстановить БД
uv run alembic upgrade head      # Применить миграции через alembic
```

## 🚀 Развертывание

### 🐳 Docker (рекомендуется)

#### Автоматическое развертывание

```bash
# Клонирование репозитория
git clone <your-repo-url>
cd hse_bot_ai_masters

# Настройка конфигурации
cp src/config/.env.example src/config/.env
nano src/config/.env  # отредактируйте настройки

# Добавление Google Service Account
# Поместите creds.json в src/config/

# Запуск через Makefile
make run

# Или вручную
docker-compose up -d --build
```

#### Ручное развертывание

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

### 🐍 Локальное развертывание

```bash
# Установка uv (если не установлен)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Установка зависимостей
uv sync

# Настройка переменных окружения
export $(cat src/config/.env | xargs)

# Запуск в полном режиме
make run
# или
uv run python main.py full
```

### 🔄 Обновление

#### Подготовка сервера (первый раз)

Если вы только что сделали `git pull` и получили обновления с `uv`, `Makefile` и другими изменениями:

1. **Установите make (если не установлен):**
```bash
# Проверьте, установлен ли make
which make

# Если нет, установите (Ubuntu/Debian)
sudo apt install make

# Для CentOS/RHEL
sudo yum install make
```

2. **Установите uv (если не установлен):**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env  # или перезапустите терминал

# Проверьте установку
uv --version
```

3. **Установите зависимости:**
```bash
uv sync
```

4. **Пересоберите и запустите контейнеры:**
```bash
docker-compose build --no-cache
docker-compose up -d

# Примените миграции (если нужно)
docker exec hse_bot_app uv run python main.py migrate
```

#### Обычное обновление

С помощью Makefile (рекомендуется, если `make` установлен):
```bash
make update
```

Или вручную:
```bash
# Остановка сервисов
docker-compose down

# Обновление кода
git pull

# Пересборка и запуск
docker-compose build --no-cache
docker-compose up -d

# Применение миграций
docker exec hse_bot_app uv run python main.py migrate
```

**Примечание:** Если при обновлении вы получили новые зависимости или изменилась структура проекта, выполните команды из раздела "Подготовка сервера (первый раз)" выше.

### 📋 Основные команды Makefile

```bash
make help           # Показать все доступные команды

# Установка
make install-uv     # Установить uv менеджер пакетов
make setup          # Полная установка (uv + зависимости)
make install        # Установить зависимости
make install-dev    # Установить зависимости для разработки

# Запуск
make run            # Запустить бота с синхронизацией и уведомлениями
make logs           # Просмотреть логи за сегодня

# Проверка кода
make lint           # Проверить код с помощью ruff
make lint-fix       # Автоматически исправить проблемы с кодом
make format         # Отформатировать код

# Обслуживание
make clean          # Очистить временные файлы
make update         # Обновить проект (остановить, git pull, перезапустить)
make clean-docker   # Очистить неиспользуемые Docker образы и контейнеры
make db             # Подключиться к базе данных PostgreSQL
```

## ✅ Проверка работы

### 🔍 Проверка статуса контейнеров

```bash
# Статус всех контейнеров
docker-compose ps

# Детальная информация
docker-compose ps --services
```

### 📊 Проверка логов

```bash
# Логи приложения
docker-compose logs -f app

# Логи базы данных
docker-compose logs -f db

# Логи всех сервисов
docker-compose logs -f

# Последние 100 строк логов
docker-compose logs --tail=100 app
```

### 🗄️ Проверка базы данных

```bash
# Подключение к БД (или используйте: make db)
docker-compose exec db psql -U postgres -d hse_bot_db
# Или через Makefile:
make db

# Проверка таблиц
docker-compose exec db psql -U postgres -d hse_bot_db -c "\dt"

# Проверка пользователей
docker-compose exec db psql -U postgres -d hse_bot_db -c "SELECT COUNT(*) FROM users;"

# Проверка дедлайнов
docker-compose exec db psql -U postgres -d hse_bot_db -c "SELECT COUNT(*) FROM deadlines;"
```

### 🤖 Проверка работы бота

```bash
# Поиск сообщений о запуске бота
docker-compose logs app | grep "Bot started"

# Проверка планировщика
docker-compose logs app | grep "scheduler"

# Проверка синхронизации
docker-compose logs app | grep "sync"
```

### 🌐 Проверка внешних подключений

```bash
# Тест подключения к Google Sheets
docker-compose exec app python -c "
from src.core.sync.gsheets_syncer import sheets_manager
import asyncio
asyncio.run(sheets_manager.test_connection())
"

# Тест Telegram API
docker-compose exec app python -c "
import os
from aiogram import Bot
import asyncio

async def test_bot():
    bot = Bot(token=os.getenv('BOT_TOKEN'))
    me = await bot.get_me()
    print(f'Bot: @{me.username}')
    await bot.session.close()

asyncio.run(test_bot())
"
```

## 📊 Мониторинг и обслуживание

### 📈 Мониторинг ресурсов

```bash
# Использование ресурсов контейнерами
docker stats

# Использование дискового пространства
df -h

# Размер логов
du -sh logs/

# Размер бэкапов
du -sh backups/
```

### 🔄 Управление сервисами

```bash
# Перезапуск приложения
docker-compose restart app

# Перезапуск всех сервисов
docker-compose restart

# Остановка всех сервисов
docker-compose down

# Запуск в фоновом режиме
docker-compose up -d
```

### 📝 Управление логами

```bash
# Просмотр логов в реальном времени
docker-compose logs -f app

# Очистка старых логов
docker-compose exec app find logs/ -name "*.log" -mtime +7 -delete

# Ротация логов (если настроена)
docker-compose exec app logrotate -f /etc/logrotate.conf
```

### 🗄️ Управление базой данных

```bash
# Создание бэкапа
./scripts/backup-db.sh

# Восстановление из бэкапа
./scripts/restore-db.sh backups/latest.sql.gz

# Применение миграций (если нужно)
docker exec hse_bot_app python main.py migrate

# Проверка статуса миграций (если нужно)
docker exec hse_bot_app alembic current
```

## 🌐 Настройка для продакшена

### 🔒 Безопасность

#### Настройка firewall

```bash
# Ubuntu/Debian (ufw)
sudo ufw allow 22    # SSH
sudo ufw allow 80    # HTTP
sudo ufw allow 443   # HTTPS
sudo ufw enable

# CentOS/RHEL (firewalld)
sudo firewall-cmd --permanent --add-service=ssh
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

#### Настройка SSL (Let's Encrypt)

```bash
# Установка Certbot
sudo apt install certbot nginx  # Ubuntu/Debian
sudo yum install certbot nginx  # CentOS/RHEL

# Получение сертификата
sudo certbot --nginx -d your-domain.com

# Автоматическое обновление
sudo crontab -e
# Добавьте: 0 12 * * * /usr/bin/certbot renew --quiet
```

### 🌐 Reverse Proxy (Nginx)

Создайте файл `/etc/nginx/sites-available/hse-bot`:

```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    # Редирект на HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;
    
    # SSL сертификаты
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    
    # SSL настройки
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512:ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    
    # Adminer для управления БД
    location /adminer {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    # Статус страница (опционально)
    location /status {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Активируйте конфигурацию:

```bash
sudo ln -s /etc/nginx/sites-available/hse-bot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 🔧 Оптимизация производительности

#### Настройка Docker

Обновите `docker-compose.yml`:

```yaml
services:
  app:
    # ... существующие настройки ...
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: '0.5'
        reservations:
          memory: 256M
          cpus: '0.25'
    restart: unless-stopped
    
  db:
    # ... существующие настройки ...
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: '1.0'
        reservations:
          memory: 512M
          cpus: '0.5'
    restart: unless-stopped
```

#### Настройка PostgreSQL

Создайте файл `init-scripts/02-postgres-optimization.sql`:

```sql
-- Оптимизация PostgreSQL для продакшена
ALTER SYSTEM SET shared_buffers = '256MB';
ALTER SYSTEM SET effective_cache_size = '1GB';
ALTER SYSTEM SET maintenance_work_mem = '64MB';
ALTER SYSTEM SET checkpoint_completion_target = 0.9;
ALTER SYSTEM SET wal_buffers = '16MB';
ALTER SYSTEM SET default_statistics_target = 100;
ALTER SYSTEM SET random_page_cost = 1.1;
ALTER SYSTEM SET effective_io_concurrency = 200;
ALTER SYSTEM SET work_mem = '4MB';
ALTER SYSTEM SET min_wal_size = '1GB';
ALTER SYSTEM SET max_wal_size = '4GB';

-- Перезагрузка конфигурации
SELECT pg_reload_conf();
```

## 💾 Резервное копирование

### 🔄 Автоматические бэкапы

#### Настройка cron

```bash
# Настройка ежедневного бэкапа в 02:00
./scripts/setup-backup-cron.sh -t 02:00

# Проверка настроенных задач
./scripts/setup-backup-cron.sh --show

# Удаление задач бэкапа
./scripts/setup-backup-cron.sh --remove
```

#### Ручные бэкапы

```bash
# Создание бэкапа
./scripts/backup-db.sh

# Восстановление из бэкапа
./scripts/restore-db.sh backups/hse_bot_db_backup_20240101_120000.sql.gz

# Восстановление с принудительным пересозданием
./scripts/restore-db.sh --force --drop-existing backups/latest.sql.gz
```

### 📦 Бэкап конфигурации

```bash
# Создание архива конфигурации
tar -czf config-backup-$(date +%Y%m%d).tar.gz \
    src/config/.env \
    src/config/creds.json \
    docker-compose.yml \
    scripts/

# Восстановление конфигурации
tar -xzf config-backup-20240101.tar.gz
```

### ☁️ Облачные бэкапы

#### AWS S3

```bash
# Установка AWS CLI
pip install awscli

# Настройка
aws configure

# Загрузка бэкапа
aws s3 cp backups/latest.sql.gz s3://your-bucket/hse-bot-backups/

# Скачивание бэкапа
aws s3 cp s3://your-bucket/hse-bot-backups/latest.sql.gz backups/
```

#### Google Cloud Storage

```bash
# Установка gsutil
curl https://sdk.cloud.google.com | bash
source ~/.bashrc

# Настройка
gcloud auth login

# Загрузка бэкапа
gsutil cp backups/latest.sql.gz gs://your-bucket/hse-bot-backups/

# Скачивание бэкапа
gsutil cp gs://your-bucket/hse-bot-backups/latest.sql.gz backups/
```

## 🔧 Устранение неполадок

### 🚨 Общие проблемы

#### Контейнер не запускается

```bash
# Проверка логов
docker-compose logs app

# Проверка конфигурации
docker-compose config

# Пересборка без кэша
docker-compose build --no-cache

# Проверка ресурсов
docker system df
docker system prune  # Очистка неиспользуемых ресурсов
```

#### Ошибки подключения к БД

```bash
# Проверка статуса БД
docker-compose exec db pg_isready -U postgres

# Проверка переменных окружения
docker-compose exec app env | grep DATABASE_URL

# Ручное подключение к БД
docker-compose exec db psql -U postgres -d hse_bot_db

# Проверка логов БД
docker-compose logs db
```

#### Проблемы с миграциями

```bash
# Проверка статуса миграций
docker-compose exec app alembic current

# Применение миграций вручную
docker-compose exec app alembic upgrade head

# Откат миграций (осторожно!)
docker-compose exec app alembic downgrade -1

# Создание новой миграции
docker-compose exec app alembic revision --autogenerate -m "description"
```

#### Проблемы с Google Sheets

```bash
# Проверка файла creds
docker-compose exec app ls -la /app/src/config/creds.json

# Тест подключения
docker-compose exec app python -c "
from src.core.sync.gsheets_syncer import sheets_manager
import asyncio
asyncio.run(sheets_manager.test_connection())
"

# Проверка прав доступа к Google Sheets
# Убедитесь, что Service Account добавлен в документ
```

#### Проблемы с уведомлениями

```bash
# Проверка планировщика
docker-compose logs app | grep "scheduler"

# Проверка уведомлений
docker-compose logs app | grep "notification"

# Ручная отправка уведомлений
docker-compose exec app python -c "
from src.bot.services.scheduled_notification_sender import scheduled_notification_sender
from src.bot.bot import hse_bot
import asyncio
asyncio.run(scheduled_notification_sender.send_scheduled_notifications(hse_bot.bot))
"
```

### 🔍 Диагностика

#### Проверка системы

```bash
# Использование ресурсов
docker stats

# Использование диска
df -h
du -sh logs/ backups/

# Сетевые подключения
netstat -tulpn | grep :5432  # PostgreSQL
netstat -tulpn | grep :8080  # Adminer
```

#### Проверка логов

```bash
# Поиск ошибок
docker-compose logs app | grep -i error

# Поиск предупреждений
docker-compose logs app | grep -i warning

# Статистика логов
docker-compose logs app | wc -l
```

#### Проверка базы данных

```bash
# Размер базы данных
docker-compose exec db psql -U postgres -d hse_bot_db -c "
SELECT pg_size_pretty(pg_database_size('hse_bot_db'));
"

# Размер таблиц
docker-compose exec db psql -U postgres -d hse_bot_db -c "
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
FROM pg_tables 
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
"

# Статистика таблиц
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

### 🆘 Экстренное восстановление

#### Полное восстановление

```bash
# Остановка всех сервисов
docker-compose down

# Восстановление из бэкапа
./scripts/restore-db.sh --force --drop-existing backups/latest.sql.gz

# Запуск сервисов
docker-compose up -d

# Проверка работы
docker-compose logs -f app
```

#### Восстановление конфигурации

```bash
# Остановка сервисов
docker-compose down

# Восстановление конфигурации
tar -xzf config-backup-20240101.tar.gz

# Проверка конфигурации
docker-compose config

# Запуск сервисов
docker-compose up -d
```

### 📞 Получение помощи

#### Сбор информации для отчета

```bash
# Создание отчета о системе
cat > system-report.txt << EOF
=== SYSTEM INFO ===
$(uname -a)
$(docker --version)
$(docker-compose --version)

=== CONTAINER STATUS ===
$(docker-compose ps)

=== RECENT LOGS ===
$(docker-compose logs --tail=50 app)

=== DATABASE STATUS ===
$(docker-compose exec db psql -U postgres -d hse_bot_db -c "SELECT version();")

=== DISK USAGE ===
$(df -h)
$(du -sh logs/ backups/ 2>/dev/null || echo "No logs/backups found")
EOF

echo "Отчет сохранен в system-report.txt"
```

## 📚 Связанная документация

- **[../README.md](../README.md)** - Основная документация и обзор возможностей
- **[TECHNICAL.md](TECHNICAL.md)** - Техническая документация и архитектура
- **[UPDATES.md](UPDATES.md)** - История обновлений и версий

---

<div align="center">

**🚀 HSE AI Deadlines Bot - Deployment Guide**

*Подробное руководство по развертыванию и эксплуатации*

</div>
