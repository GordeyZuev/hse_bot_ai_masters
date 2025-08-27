# Техническая документация

## 🏗️ Архитектура системы

### Общая схема

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

### Слои приложения

1. **Presentation Layer** - Telegram Bot Interface
2. **Business Logic Layer** - Services и Core Logic
3. **Data Access Layer** - Database Models и Repositories
4. **External Integration Layer** - Google Sheets API

## 🔧 Компоненты системы

### Bot Layer (`src/bot/`)

#### Handlers
- **admin.py** - Административные функции
- **deadlines.py** - Просмотр дедлайнов
- **help.py** - Справочная система
- **settings.py** - Настройки пользователя
- **start.py** - Стартовые команды
- **subscriptions.py** - Управление подписками

#### Middlewares
- **database.py** - Автоматическое создание/обновление пользователей

#### Services
- **admin_service.py** - Административные операции
- **notification_service.py** - Система уведомлений
- **subscription_service.py** - Управление подписками

#### States
- **states.py** - FSM состояния для диалогов

### Core Layer (`src/core/`)

#### Database
- **database.py** - DatabaseManager, подключение к БД

#### Models
- **models.py** - SQLAlchemy модели
- **subjects_data.py** - Справочник предметов

#### Sync
- **data_syncer.py** - Основная логика синхронизации
- **gsheets_syncer.py** - Google Sheets API
- **scheduler.py** - APScheduler задачи

## 📊 Модели данных

### User
```python
class User(Base):
    id: int                    # Telegram user ID
    username: str             # Telegram username
    first_name: str           # Имя пользователя
    last_name: str            # Фамилия пользователя
    is_admin: bool            # Флаг администратора
    notification_enabled: bool # Включены ли уведомления
    notification_time: time   # Время уведомлений
    created_at: datetime      # Дата регистрации
    updated_at: datetime      # Дата последнего обновления
```

### Subject
```python
class Subject(Base):
    id: int                   # ID предмета
    name: str                 # Название предмета
    short_name: str           # Короткое название
    is_active: bool           # Активен ли предмет
    created_at: datetime      # Дата создания
    updated_at: datetime      # Дата обновления
```

### Deadline
```python
class Deadline(Base):
    id: int                   # ID дедлайна
    subject_id: int           # ID предмета
    title: str                # Название задания
    description: str          # Описание
    due_date: date            # Дата дедлайна
    is_active: bool           # Активен ли дедлайн
    created_at: datetime      # Дата создания
    updated_at: datetime      # Дата обновления
```

### Subscription
```python
class Subscription(Base):
    id: int                   # ID подписки
    user_id: int              # ID пользователя
    subject_id: int           # ID предмета
    created_at: datetime      # Дата подписки
```

### Notification
```python
class Notification(Base):
    id: int                   # ID уведомления
    user_id: int              # ID пользователя
    deadline_id: int          # ID дедлайна
    notification_type: str    # Тип уведомления (3_days, 1_day, same_day)
    sent_at: datetime         # Время отправки
    is_successful: bool       # Успешно ли отправлено
```

## 🔄 Жизненный цикл данных

### Синхронизация с Google Sheets

1. **Планировщик** запускает задачу синхронизации каждые 6 часов
2. **GSheetsSyncer** получает данные из Google Sheets
3. **DataSyncer** обрабатывает и сохраняет данные в БД
4. Обновляются таблицы `subjects` и `deadlines`

### Система уведомлений

1. **Планировщик** запускает проверку уведомлений каждый час
2. **NotificationService** находит дедлайны для уведомления
3. Отправляются уведомления за 3 дня, 1 день и в день дедлайна
4. Результаты сохраняются в таблицу `notifications`

### Обработка команд пользователя

1. **Middleware** автоматически создает/обновляет пользователя
2. **Handler** обрабатывает команду
3. **Service** выполняет бизнес-логику
4. Результат отправляется пользователю

## 🛠️ API и интеграции

### Google Sheets API

#### Структура таблицы
```
| Предмет | Задание | Описание | Дедлайн | Статус |
|---------|---------|----------|---------|--------|
| МО      | ДЗ 1    | Описание | 2025-09-01 | active |
```

#### Методы GSheetsSyncer
- `get_sheet_data()` - Получение данных из таблицы
- `parse_deadlines()` - Парсинг дедлайнов
- `validate_data()` - Валидация данных

### Telegram Bot API

#### Основные методы
- `send_message()` - Отправка сообщений
- `edit_message_text()` - Редактирование сообщений
- `answer_callback_query()` - Ответ на callback
- `send_document()` - Отправка файлов
