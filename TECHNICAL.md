## Архитектура

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

### Слои
- Bot (`src/bot/`): handlers, middlewares, services
- Core (`src/core/`): database, models, sync, scheduler
- Utils (`src/utils/`): логирование и утилиты

### Потоки
- Синхронизация: Scheduler → GSheetsSyncer → DataSyncer → БД
- Уведомления: Scheduler → NotificationService/NotificationSender → Telegram
- Обработка команд: Middleware → Handler → Service → Ответ

Ключевые связи:
- `subscriptions.user_id → users.id`, `subscriptions.subject_id → subjects.id`
- `deadlines.subject_id → subjects.id`
- `notifications.user_id → users.id`, `notifications.deadline_id → deadlines.id`

---
Детали запуска и конфигурации: см. `README.md`.