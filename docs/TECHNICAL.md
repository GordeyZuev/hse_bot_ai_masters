# 🔧 Техническая документация HSE AI Deadlines Bot

> Подробное описание архитектуры, компонентов и технических решений

**📖 [← Вернуться к основной документации](../README.md)**

## 📋 Содержание

- [Архитектура системы](#-архитектура-системы)
- [Компоненты и слои](#-компоненты-и-слои)
- [Инфраструктура проекта](#-инфраструктура-проекта)
- [База данных](#-база-данных)
- [API и интеграции](#-api-и-интеграции)
- [Планировщик задач](#-планировщик-задач)
- [Система уведомлений](#-система-уведомлений)
- [Система мгновенных уведомлений об изменениях](#-система-мгновенных-уведомлений-об-изменениях)
- [Безопасность](#-безопасность)
- [Производительность](#-производительность)
- [Мониторинг и логирование](#-мониторинг-и-логирование)

## 🏗️ Архитектура системы

### 📊 Общая схема

```
┌───────────────────────────────────────────────────── Application (Python) ─────────────────────────────────────────────────────┐
│                                                                                                                                │
│  ┌───────────────┐        ┌──────────────────┐        ┌────────────────────┐        ┌──────────────────────────────┐         │
│  │   Handlers    │  calls │    Services      │  use   │   Core / DB Layer   │  I/O   │       Scheduler (APS)        │         │
│  │ (bot/handlers)├────────► (bot/services)   ├────────► (core/database,     ├────────►  sync, notifications,       │         │
│  │               │        │  admin, notify)  │        │  models, sync)      │        │  cleanup (cron-like jobs)    │         │
│  └───────▲───────┘        └─────────▲────────┘        └──────────▲─────────┘        └──────────────▲────────────────┘         │
│          │ Inline-callbacks / cmds            │ DI / business logic           │ SQLAlchemy (async)         │ jobs/triggers       │
│  ┌───────┴────────┐                           │                               │                            │                     │
│  │  Middlewares   │───────────────────────────┘                               │                            │                     │
│  │(bot/middlewares)│   user/session mgmt                                          │                            │                     │
│  └───────▲────────┘                                                               │                            │                     │
│          │ Telegram API                                                            │                            │                     │
│  ┌───────┴──────────────┐                                              ┌───────────┴──────────┐                 │                     │
│  │       Bot (aiogram)  │                                              │  Google Sheets API   │◄────────────────┘                     │
│  │    (bot/bot.py)      │                                              │ (core/sync/gsheets)  │                                       │
│  └─────────▲────────────┘                                              └───────────▲──────────┘                                       │
│            │ Polling                                                             │ HTTP                                                 │
│            │                                                                      │                                                     │
│  ┌─────────┴──────────┐                                                ┌──────────┴──────────┐                                        │
│  │     Logger         │                                                │     PostgreSQL      │                                        │
│  │   (utils/logger)   │────────────────────────────────────────────────►   (Docker: db)     │                                        │
│  └────────────────────┘            file logs (./logs)                  └─────────────────────┘                                        │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 🔄 Потоки данных

#### 1. **Синхронизация данных**
```
Scheduler → GSheetsSyncer → DataSyncer → DatabaseManager → PostgreSQL
    ↓              ↓              ↓              ↓
  Timer        HTTP API      Transform      SQLAlchemy
```

#### 2. **Обработка команд пользователя**
```
Telegram → Middleware → Handler → Service → DatabaseManager → Response
    ↓           ↓          ↓         ↓            ↓
  Webhook    User Mgmt   Business   Data        SQLAlchemy
```

#### 3. **Система уведомлений**
```
Scheduler → NotificationScheduler → ScheduledNotification → NotificationSender → Telegram
    ↓              ↓                        ↓                      ↓
  Timer        Planning                Database              HTTP API
```

#### 4. **Система мгновенных уведомлений об изменениях**
```
Sync (DataSyncer) → Changes Detector → NotificationSender.send_immediate_deadline_changes → Telegram
    ↓                    ↓                           ↓
  Sheets            Diff by rows                 Group & send
```

## 🧩 Компоненты и слои

### 🤖 Bot Layer (`src/bot/`)

#### Handlers (`src/bot/handlers/`)
- **`start.py`** - Команды `/start`, `/help`
- **`deadlines.py`** - Просмотр дедлайнов `/deadlines`
- **`subscriptions.py`** - Управление подписками `/sub`, `/unsub`
- **`settings.py`** - Настройки уведомлений `/settings`
- **`admin.py`** - Админ-панель `/admin`

#### Services (`src/bot/services/`)
- **`notification_service.py`** - Управление настройками уведомлений
- **`notification_scheduler_service.py`** - Планирование уведомлений
- **`scheduled_notification_sender.py`** - Отправка уведомлений
- Батч‑обработка по пользователям, параллельная отправка (`asyncio.gather`), fail‑safe пометка задержек и кнопка «📅 Дедлайны» в сообщениях
- **`admin_service.py`** - Админские функции
- **`deadline_service.py`** - Работа с дедлайнами
- **`subscription_service.py`** - Управление подписками

#### Middlewares (`src/bot/middlewares/`)
- **`database.py`** - Автоматическое создание пользователей и работа с БД

### 🏗️ Core Layer (`src/core/`)

#### Database (`src/core/database/`)
- **`database.py`** - DatabaseManager для работы с PostgreSQL
- **`models.py`** - SQLAlchemy модели данных

#### Models (`src/core/models/`)
- **`models.py`** - Определения таблиц и связей
- **`subjects_data.py`** - Статические данные о предметах

#### Sync (`src/core/sync/`)
- **`data_syncer.py`** - Основная логика синхронизации
- **`gsheets_syncer.py`** - Работа с Google Sheets API

#### Scheduler (`src/core/scheduler.py`)
- **`scheduler.py`** - Единый планировщик задач (APScheduler)
- Cron‑триггеры: синхронизация **ежечасно на :00 (UTC)**, уведомления **каждые 15 минут (UTC)**, ежедневная очистка. Настройки надёжности: `coalesce=true`, `misfire_grace_time=900`.

### 🛠️ Utils (`src/utils/`)
- **`logger.py`** - Настройка логирования
- **`time.py`** - Утилиты для работы с временем и часовыми поясами

## 🔧 Инфраструктура проекта

### 📦 Управление зависимостями
- **`uv`** - Современный и быстрый менеджер пакетов Python (альтернатива `pip`)
- **`pyproject.toml`** - Конфигурация проекта и зависимостей
- **`uv.lock`** - Зафиксированные версии зависимостей для воспроизводимых сборок

### 🔨 Build и развертывание
- **`Makefile`** - Упрощённое управление проектом через make-команды
  - `make run` - Запуск бота
  - `make lint` - Проверка кода
  - `make lint-fix` - Автоматическое исправление кода
  - `make format` - Форматирование кода
  - `make update` - Автоматическое обновление (git pull, rebuild, restart, migrate)
  - `make logs` - Просмотр логов
  - `make clean` - Очистка временных файлов
- **`docker-compose.yml`** - Оркестрация контейнеров для развертывания
- **`Dockerfile`** - Образ для контейнеризации приложения

### 🔍 Качество кода
- **`ruff`** - Быстрый линтер и форматтер Python кода
- **`alembic`** - Миграции базы данных
- Автоматическая проверка кода при разработке

### 📚 Документация
- **README.md** - Основная документация и быстрый старт
- **docs/DEPLOYMENT.md** - Руководство по развертыванию
- **docs/TECHNICAL.md** - Техническая документация (этот файл)
- **docs/UPDATES.md** - История обновлений и версий

## 📦 Зависимости

### Основные библиотеки
- **`aiogram`** (3.22.0) - Telegram Bot API framework
- **`SQLAlchemy`** (2.0.43) - ORM для работы с базой данных
- **`asyncpg`** (0.30.0) - Асинхронный PostgreSQL драйвер
- **`APScheduler`** (3.11.0) - Планировщик задач
- **`pytz`** (2025.2) - Работа с часовыми поясами
- **`timezonefinder`** (8.0.0) - Определение часового пояса по координатам

### Интеграции
- **`gspread`** (6.0.2) - Google Sheets API
- **`google-auth`** (2.40.3) - Аутентификация Google API

### Утилиты
- **`loguru`** (0.7.3) - Продвинутое логирование
- **`python-dotenv`** (1.1.1) - Загрузка переменных окружения
- **`alembic`** (1.16.4) - Миграции базы данных
- **`ruff`** (>=0.8.0) - Быстрый линтер и форматтер Python кода

## 📚 Связанная документация

- **[../README.md](../README.md)** - Основная документация и обзор возможностей
- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Руководство по развертыванию и эксплуатации
- **[UPDATES.md](UPDATES.md)** - История обновлений и версий

---

<div align="center">

**🔧 HSE AI Deadlines Bot - Technical Documentation**

*Подробная техническая документация архитектуры и компонентов*

</div>