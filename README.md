# HSE Bot AI Masters - Телеграм бот для уведомлений о дедлайнах

🎓 Телеграм бот для студентов магистерской программы НИУ ВШЭ, который отправляет уведомления о приближающихся дедлайнах на основе данных из Google Sheets.

## 🚀 Возможности

- **📚 Подписки на дисциплины** - выберите предметы, по которым хотите получать уведомления
- **⚙️ Настройка уведомлений** - до 2 уведомлений с настраиваемым временем
- **🔄 Автоматическая синхронизация** - данные обновляются из Google Sheets каждые 30 минут
- **📱 Удобный интерфейс** - интуитивно понятные команды и inline-клавиатуры
- **🛡️ Надежная доставка** - система повторных попыток и мониторинга доставки
- **📊 Масштабируемость** - поддержка до 800+ пользователей

## 🏗️ Архитектура

```
├── src/
│   ├── bot/                 # Основной код бота
│   │   ├── handlers/        # Обработчики команд и callback'ов
│   │   ├── middlewares/     # Middleware для логирования и БД
│   │   ├── services/        # Бизнес-логика (уведомления, Google Sheets)
│   │   ├── main.py         # Точка входа
│   │   └── scheduler.py    # Планировщик задач
│   ├── db/                 # Работа с базой данных
│   │   ├── models.py       # SQLAlchemy модели
│   │   ├── crud.py         # CRUD операции
│   │   └── session.py      # Настройка сессий БД
│   └── utils/              # Утилиты
│       ├── config.py       # Конфигурация
│       └── logger.py       # Система логирования
├── tests/                  # Тесты
├── scripts/               # Скрипты для мониторинга
├── config/               # Конфигурационные файлы
└── alembic/             # Миграции БД
```

## 🛠️ Технологический стек

- **Python 3.11+** - основной язык
- **aiogram 3.x** - фреймворк для Telegram Bot API
- **PostgreSQL** - основная база данных
- **Redis** - кеширование и очереди
- **SQLAlchemy 2.0** - ORM для работы с БД
- **Alembic** - миграции базы данных
- **APScheduler** - планировщик задач
- **Google Sheets API** - интеграция с таблицами
- **Loguru** - система логирования
- **Docker** - контейнеризация
- **pytest** - тестирование

## 📋 Требования

- Python 3.11+
- PostgreSQL 13+
- Redis 6+
- Docker и Docker Compose (опционально)

## 🚀 Быстрый старт

### 1. Клонирование репозитория

```bash
git clone <repository-url>
cd hse_bot_ai_masters
```

### 2. Настройка окружения

```bash
# Создание виртуального окружения
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# или
.venv\Scripts\activate     # Windows

# Установка зависимостей
pip install -r requirements.txt
```

### 3. Конфигурация

Скопируйте и настройте файл конфигурации:

```bash
cp config/.env.example config/.env
```

Заполните необходимые переменные в `config/.env`:

```env
# Telegram Bot
BOT_TOKEN=your_telegram_bot_token_here

# Database
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/hse_bot_db

# Google Sheets
GOOGLE_SHEETS_URL=your_google_sheets_url
GOOGLE_CREDS_FILE=config/creds.json

# Redis
REDIS_URL=redis://localhost:6379/0
```

### 4. Настройка Google Sheets API

1. Создайте проект в [Google Cloud Console](https://console.cloud.google.com/)
2. Включите Google Sheets API
3. Создайте Service Account и скачайте JSON ключ
4. Поместите ключ в `config/creds.json`
5. Предоставьте доступ к таблице для email из Service Account

### 5. Настройка базы данных

```bash
# Установка PostgreSQL (если не установлен)
brew install postgresql@15
brew services start postgresql@15

# Добавление PostgreSQL в PATH
echo 'export PATH="/opt/homebrew/opt/postgresql@15/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

# Создание пользователя postgres с паролем
createuser -s postgres
psql postgres -c "ALTER USER postgres PASSWORD 'password';"

# Создание базы данных
createdb hse_bot_db

# Применение миграций
alembic upgrade head
```

### 6. Запуск бота

```bash
# Запуск в режиме разработки
python -m src.bot.main

# Или через Docker Compose
docker-compose up -d
```

## 🐳 Развертывание с Docker

### ⚠️ Важно: Проблемы с Docker?

Если у вас возникают проблемы с Docker (например, "Cannot connect to the Docker daemon"), см. подробное руководство: **[docs/docker-troubleshooting.md](docs/docker-troubleshooting.md)**

### Быстрое развертывание

```bash
# 1. Убедитесь, что Docker Desktop запущен (для macOS)
# 2. Запуск всех сервисов
docker-compose up -d

# Просмотр логов
docker-compose logs -f bot

# Остановка
docker-compose down
```

### Альтернативный запуск без Docker

Если Docker не работает, можете запустить локально:

```bash
# Установка зависимостей системы (macOS)
brew install postgresql@15 redis
brew services start postgresql@15 redis

# Создание БД
createdb hse_bot_db

# Настройка окружения для локального запуска
# Отредактируйте config/.env:
# DATABASE_URL=postgresql+asyncpg://postgres@localhost:5432/hse_bot_db
# REDIS_URL=redis://localhost:6379/0

# Запуск бота
python -m src.bot.main
```

### Продакшн развертывание

```bash
# Сборка для продакшна
docker-compose -f docker-compose.prod.yml up -d

# Мониторинг
docker-compose -f docker-compose.prod.yml logs -f
```

## 📊 Мониторинг и производительность

### Проверка состояния системы

```bash
# Одноразовая проверка метрик
python scripts/performance_monitor.py

# Непрерывный мониторинг (1 час, каждые 60 секунд)
python scripts/performance_monitor.py monitor 3600 60

# Нагрузочный тест
python scripts/performance_monitor.py load
```

### Запуск тестов производительности

```bash
# Все тесты производительности
pytest tests/test_performance.py -v

# Конкретный тест
pytest tests/test_performance.py::TestPerformance::test_full_system_load -v
```

## 🔧 Конфигурация

### Основные настройки

Основные настройки находятся в `config/.env`:

- `BOT_TOKEN` - токен Telegram бота
- `DATABASE_URL` - строка подключения к PostgreSQL
- `REDIS_URL` - строка подключения к Redis
- `GOOGLE_SHEETS_URL` - ссылка на Google таблицу
- `LOG_LEVEL` - уровень логирования (DEBUG, INFO, WARNING, ERROR)

### Настройки производительности

Дополнительные настройки производительности в `config/performance.yml`:

- Размеры батчей для уведомлений
- Интервалы выполнения задач
- Лимиты памяти и CPU
- Настройки кеширования

## 📝 Использование

### Команды бота

- `/start` - Регистрация и приветствие
- `/help` - Справка по командам
- `/subscribe` - Подписка на дисциплины
- `/my_subscriptions` - Просмотр активных подписок
- `/settings` - Настройки уведомлений

### Настройка уведомлений

1. Количество уведомлений: 1 или 2
2. Время первого уведомления: от 30 минут до 3 дней
3. Время второго уведомления: от 30 минут до 12 часов
4. Включение/выключение уведомлений

### Формат Google Sheets

Таблица должна содержать следующие колонки:

| ID | Дисциплина | Название ДЗ | Источник (Link) | Мягкий Дедлайн | Жесткий Дедлайн | Дней до | Примечание |
|----|------------|-------------|-----------------|----------------|-----------------|---------|------------|
| 1  | Математика | ДЗ №1      | https://...     | 01.01.2024     | 02.01.2024     | 5       | Важное ДЗ  |

## 🧪 Тестирование

### Запуск тестов

```bash
# Все тесты
pytest

# Тесты производительности
pytest tests/test_performance.py

# С покрытием кода
pytest --cov=src tests/
```

### Типы тестов

- **Unit тесты** - тестирование отдельных компонентов
- **Integration тесты** - тестирование взаимодействия компонентов
- **Performance тесты** - тестирование производительности
- **Load тесты** - тестирование под нагрузкой

## 📈 Масштабирование

Система оптимизирована для работы с 800+ пользователями:

### Оптимизации базы данных

- Индексы на часто используемых полях
- Connection pooling
- Batch операции для массовых обновлений

### Оптимизации уведомлений

- Батчинг сообщений (50 сообщений в батче)
- Rate limiting (25 сообщений в секунду)
- Асинхронная обработка
- Система повторных попыток

### Мониторинг производительности

- Автоматический сбор метрик
- Предупреждения о превышении лимитов
- Логирование медленных операций

## 🔒 Безопасность

- Валидация всех входящих данных
- Rate limiting для предотвращения спама
- Безопасное хранение токенов и ключей
- Логирование всех действий пользователей

## 🐛 Отладка

### Логи

Логи сохраняются в директории `logs/`:

- `hse_bot_YYYYMMDD.log` - основные логи
- `performance_metrics_*.json` - метрики производительности
- `critical_metrics_*.json` - критические события

### Полезные команды

```bash
# Просмотр логов в реальном времени
tail -f logs/hse_bot_$(date +%Y%m%d).log

# Поиск ошибок
grep -i error logs/hse_bot_*.log

# Анализ производительности
python scripts/performance_monitor.py
```

## 🤝 Разработка

### Структура проекта

- Следуем принципам Clean Architecture
- Разделение на слои: handlers, services, repositories
- Dependency Injection через конструкторы
- Асинхронное программирование везде где возможно

### Стиль кода

```bash
# Форматирование кода
black src/ tests/

# Проверка стиля
flake8 src/ tests/

# Сортировка импортов
isort src/ tests/
```

### Создание миграций

```bash
# Создание новой миграции
alembic revision --autogenerate -m "Description"

# Применение миграций
alembic upgrade head

# Откат миграции
alembic downgrade -1
```

## 📞 Поддержка

При возникновении проблем:

1. Проверьте логи в директории `logs/`
2. Запустите диагностику: `python scripts/performance_monitor.py`
3. Проверьте конфигурацию в `config/.env`
4. Убедитесь, что все сервисы запущены

## 📄 Лицензия

MIT License - см. файл [LICENSE](LICENSE)

## 🙏 Благодарности

- Команде aiogram за отличный фреймворк
- Сообществу Python за инструменты разработки
- НИУ ВШЭ за возможность создания этого проекта
