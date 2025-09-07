# Архитектура системы

## 🏗️ Общая схема

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Telegram Bot  │    │  Google Sheets  │    │   PostgreSQL    │
│                 │    │                 │    │                 │
│  - Handlers     │◄──►│  - Deadlines    │    │  - Users        │
│  - Middlewares  │    │  - Subjects     │    │  - Subscriptions│
│  - Services     │    │                 │    │  - Notifications│
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                    ┌─────────────────┐
                    │   Scheduler     │
                    │                 │
                    │ - Sync Tasks    │
                    │ - Notifications │
                    │ - Cleanup       │
                    └─────────────────┘
```

## 📊 Слои приложения

1. **Presentation Layer** - Telegram Bot Interface
2. **Business Logic Layer** - Services и Core Logic  
3. **Data Access Layer** - Database Models и Repositories
4. **External Integration Layer** - Google Sheets API

## 🔧 Структура компонентов

### Bot Layer (`src/bot/`)
- **handlers/** - Обработчики команд и callback'ов
- **middlewares/** - Автоматическое управление пользователями
- **services/** - Бизнес-логика (админ, уведомления, подписки)
- **states/** - FSM состояния для диалогов

### Core Layer (`src/core/`)
- **database/** - DatabaseManager, подключение к БД
- **models/** - SQLAlchemy модели и справочники
- **sync/** - Синхронизация с Google Sheets и планировщик

### Utils Layer (`src/utils/`)
- **logger.py** - Система логирования

## 🔄 Жизненный цикл данных

### Синхронизация с Google Sheets
1. **Планировщик** → Запуск каждый час
2. **GSheetsSyncer** → Получение данных из таблицы
3. **DataSyncer** → Обработка и сохранение в БД
4. **Мгновенная синхронизация** → Через админ-панель

### Система уведомлений
1. **Планировщик** → Проверка каждые 10 минут
2. **NotificationService** → Поиск дедлайнов
3. **Отправка уведомлений** → По настройкам пользователя
4. **Логирование** → Сохранение в `notification_log`

### Обработка команд
1. **Middleware** → Создание/обновление пользователя
2. **Handler** → Обработка команды
3. **Service** → Выполнение бизнес-логики
4. **Response** → Ответ пользователю

## 🗄️ Архитектура базы данных

См. диаграмму в основном README.md

---

**Примечание:** Подробная техническая документация по API, моделям данных и примерам интеграций была перенесена в основной README.md для упрощения структуры проекта.