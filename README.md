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
./scripts/setup-backup-cron.sh -t 02:00
./scripts/backup-db.sh
./scripts/restore-db.sh backups/last.sql.gz
```

### Производительность и эксплуатация
- Режим «full» запускает бот+планировщик+уведомления вместе.
- Можно разносить процессы: `python main.py bot` и `python main.py scheduler`.
- Мониторинг: `docker-compose ps`, `docker-compose logs -f app`.

### Локализация и время
- Таймзона: `TIMEZONE` (например, `Europe/Moscow`).
- Время в 24‑часовом формате.

## 🧰 Траблшутинг (кратко)
- Проверка creds: `docker-compose exec app ls -la /app/src/config/creds.json`
- Подключение к БД: `docker-compose exec db psql -U postgres -d ${POSTGRES_DB:-hse_bot_db}`
- Логи: `./logs/` или `docker-compose logs -f app`

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