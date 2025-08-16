# 🐳 Решение проблем с Docker

## Проблема: "Cannot connect to the Docker daemon"

Если вы видите ошибку:
```
unable to get image 'postgres:15-alpine': Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?
```

### Решение для macOS:

1. **Установите Docker Desktop** (если не установлен):
   - Скачайте с [docker.com](https://www.docker.com/products/docker-desktop/)
   - Установите и запустите приложение

2. **Запустите Docker Desktop**:
   - Найдите Docker Desktop в Applications
   - Запустите приложение
   - Дождитесь появления зеленого индикатора в строке меню

3. **Проверьте статус Docker**:
   ```bash
   docker --version
   docker ps
   ```

4. **Запустите проект**:
   ```bash
   docker-compose up -d
   ```

### Альтернативный способ запуска без Docker:

Если у вас проблемы с Docker, можете запустить проект локально:

#### 1. Установите зависимости системы:

**PostgreSQL:**
```bash
# Установка через Homebrew
brew install postgresql@15
brew services start postgresql@15

# Добавление PostgreSQL в PATH (добавьте в ~/.zshrc или ~/.bash_profile)
echo 'export PATH="/opt/homebrew/opt/postgresql@15/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

# Создание пользователя postgres (если нужно)
createuser -s postgres

# Создание базы данных
createdb hse_bot_db

# Или используйте полный путь:
# /opt/homebrew/opt/postgresql@15/bin/createuser -s postgres
# /opt/homebrew/opt/postgresql@15/bin/createdb hse_bot_db

# Альтернативно, создайте БД через psql:
# psql postgres -c "CREATE USER postgres WITH SUPERUSER;"
# psql postgres -c "CREATE DATABASE hse_bot_db OWNER postgres;"
```

**Redis:**
```bash
# Установка через Homebrew  
brew install redis
brew services start redis
```

#### 2. Настройте переменные окружения:

Отредактируйте `config/.env`:
```env
# Локальные подключения
DATABASE_URL=postgresql+asyncpg://postgres@localhost:5432/hse_bot_db
REDIS_URL=redis://localhost:6379/0
DB_HOST=localhost
REDIS_HOST=localhost

# Остальные настройки остаются без изменений
BOT_TOKEN=your_bot_token_here
GOOGLE_SHEETS_URL=your_google_sheets_url_here
```

#### 3. Установите Python зависимости:

```bash
# Создайте виртуальное окружение
python3.11 -m venv .venv
source .venv/bin/activate

# Установите зависимости
pip install -r requirements.txt
```

#### 4. Выполните миграции базы данных:

```bash
# Инициализация Alembic (если нужно)
alembic upgrade head
```

#### 5. Запустите бота:

```bash
python -m src.bot.main
```

## Проверка работоспособности

### Docker версия:
```bash
# Проверка контейнеров
docker-compose ps

# Логи приложения
docker-compose logs bot

# Логи базы данных
docker-compose logs postgres
```

### Локальная версия:
```bash
# Проверка подключения к БД
python -c "
import asyncio
from src.db.session import get_session
async def test():
    async with get_session() as session:
        print('✅ База данных подключена')
asyncio.run(test())
"

# Проверка Redis
redis-cli ping
```

## Мониторинг производительности

После успешного запуска:

```bash
# Запуск мониторинга
python scripts/performance_monitor.py

# Тестирование производительности
pytest tests/test_performance.py -v
```

## Частые проблемы и решения

### 1. Конфликт зависимостей Python пакетов

**Проблема 1:**
```
ERROR: Cannot install -r requirements.txt (line 2) and pydantic==2.10.3 because these package versions have conflicting dependencies.
The conflict is caused by:
    The user requested pydantic==2.10.3
    aiogram 3.13.1 depends on pydantic<2.10 and >=2.4.1
```

**Проблема 2:**
```
pydantic.errors.PydanticImportError: `BaseSettings` has been moved to the `pydantic-settings` package.
```

**Проблема 3:**
```
Building wheel for asyncpg (pyproject.toml) ... error
error: command '/usr/bin/clang' failed with exit code 1
asyncpg/pgproto/pgproto.c:1667:39: error: call to undeclared function '_PyInterpreterState_GetConfig'
```

**Проблема 4:**
```
configparser.InterpolationSyntaxError: '%' must be followed by '%' or '(', found: '%04d'
```

**Проблема 5:**
```
asyncpg.exceptions.InvalidAuthorizationSpecificationError: role "postgres" does not exist
```

**Проблема 6:**
```
ERROR | Database connection failed
ERROR | Database setup failed: Cannot connect to database
CRITICAL | Application crashed: Cannot connect to database
```

**Решение:**
Все проблемы уже исправлены в коде:
- Исправлен конфликт версий pydantic
- Исправлены импорты BaseSettings
- Обновлен asyncpg до версии, совместимой с Python 3.13
- Исправлена конфигурация Alembic (экранирован символ % в alembic.ini)
- Добавлены инструкции по созданию пользователя postgres

Если проблемы повторятся:

```bash
# Для Docker:
# Очистка Docker кеша
docker system prune -a

# Пересборка без кеша
docker-compose build --no-cache

# Запуск
docker-compose up -d

# Для локального запуска:
# Переустановка зависимостей
pip install -r requirements.txt --force-reinstall

# Если проблемы с компиляцией asyncpg, попробуйте:
pip install --no-binary asyncpg asyncpg

# Если проблемы с Alembic, проверьте экранирование % в alembic.ini

# Если проблемы с пользователем PostgreSQL:
createuser -s postgres
# Или через psql:
# psql postgres -c "CREATE USER postgres WITH SUPERUSER;"

# Если проблемы с подключением к БД:
# Вариант 1: Создать пользователя с паролем
psql postgres -c "ALTER USER postgres PASSWORD 'password';"

# Вариант 2: Изменить config/.env для подключения без пароля
# DATABASE_URL=postgresql+asyncpg://postgres@localhost:5432/hse_bot_db
# DB_PASSWORD=

# Диагностика подключения:
# 1. Проверьте, что PostgreSQL запущен
brew services list | grep postgresql
ps aux | grep postgres

# 2. Проверьте подключение к БД
psql -U postgres -d hse_bot_db -c "SELECT 1;"

# 3. Если БД не существует, создайте её
createdb -U postgres hse_bot_db

# 4. Проверьте настройки PostgreSQL
psql postgres -c "SHOW hba_file;"

# 5. Если нужно, перезапустите PostgreSQL
brew services restart postgresql@15

# 6. Проверьте порт
lsof -i :5432

# 7. Проверьте подключение без пароля
psql -U postgres -d postgres -c "SELECT current_user;"
```

### 2. Порты заняты
```bash
# Проверка занятых портов
lsof -i :5432  # PostgreSQL
lsof -i :6379  # Redis
lsof -i :8000  # Bot API

# Остановка процессов
sudo kill -9 <PID>
```

### 2. Проблемы с правами доступа
```bash
# Для Docker
sudo chown -R $USER:$USER ./logs
sudo chown -R $USER:$USER ./config

# Для локальной установки
chmod +x scripts/*.py
```

### 3. Проблемы с Google Sheets API
- Убедитесь, что файл `config/creds.json` существует
- Проверьте права доступа Service Account к таблице
- Проверьте корректность GOOGLE_SHEETS_URL

### 4. Проблемы с Telegram Bot API
- Проверьте корректность BOT_TOKEN
- Убедитесь, что бот не запущен в другом месте
- Проверьте интернет-соединение

## Логи и отладка

### Docker логи:
```bash
# Все логи
docker-compose logs -f

# Логи конкретного сервиса
docker-compose logs -f bot
docker-compose logs -f postgres
docker-compose logs -f redis
```

### Локальные логи:
```bash
# Логи приложения
tail -f logs/hse_bot.log

# Логи ошибок
tail -f logs/error.log
```

## Полезные команды

### Docker:
```bash
# Пересборка контейнеров
docker-compose build --no-cache

# Очистка системы
docker system prune -a

# Перезапуск сервисов
docker-compose restart
```

### Локальная разработка:
```bash
# Активация окружения
source .venv/bin/activate

# Обновление зависимостей
pip install -r requirements.txt --upgrade

# Форматирование кода
black src/
isort src/