# 🔧 Техническая документация HSE AI Deadlines Bot

> Подробное описание архитектуры, компонентов и технических решений

**📖 [← Вернуться к основной документации](../README.md)**

## 📋 Содержание

- [Архитектура системы](#-архитектура-системы)
- [Компоненты и слои](#-компоненты-и-слои)
- [База данных](#-база-данных)
- [API и интеграции](#-api-и-интеграции)
- [Планировщик задач](#-планировщик-задач)
- [Система уведомлений](#-система-уведомлений)
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

### 🛠️ Utils (`src/utils/`)
- **`logger.py`** - Настройка логирования

## 📚 Связанная документация

- **[../README.md](../README.md)** - Основная документация и обзор возможностей
- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Руководство по развертыванию и эксплуатации
- **[UPDATES.md](UPDATES.md)** - История обновлений и версий

---

<div align="center">

**🔧 HSE AI Deadlines Bot - Technical Documentation**

*Подробная техническая документация архитектуры и компонентов*

[![Architecture](https://img.shields.io/badge/Architecture-Modular-blue.svg)](https://github.com)
[![Database](https://img.shields.io/badge/Database-PostgreSQL-blue.svg)](https://postgresql.org)
[![Async](https://img.shields.io/badge/Async-Await-green.svg)](https://python.org)

</div>