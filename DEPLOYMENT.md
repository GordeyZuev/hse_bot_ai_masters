# 🚀 Развертывание HSE Bot

## Требования

- Docker Engine 20.10+
- Docker Compose 2.0+
- 1GB RAM, 2GB диска

## Быстрый запуск

### 1. Настройка конфигурации

```bash
# Отредактируйте файл конфигурации
nano src/config/.env
```

**Обязательно измените:**
- `BOT_TOKEN` - токен Telegram бота
- `POSTGRES_PASSWORD` и `DB_PASSWORD` - надежные пароли

### 2. Google Sheets credentials

```bash
# Поместите файл credentials.json
cp /path/to/credentials.json src/config/creds.json
```

### 3. Запуск

```bash
# Запуск всех сервисов
docker-compose up -d --build

# Проверка статуса
docker-compose ps

# Просмотр логов
docker-compose logs -f app
```

## Управление

```bash
# Остановка
docker-compose down

# Перезапуск
docker-compose restart app

# Обновление
git pull && docker-compose up -d --build
```

## Мониторинг

- **Логи приложения:** `docker-compose logs app`
- **Логи БД:** `docker-compose logs db`
- **Adminer:** http://localhost:8080
- **Файлы логов:** `./logs/`

## Устранение проблем

### База данных
```bash
# Подключение к БД
docker-compose exec db psql -U postgres -d hse_bot_db

# Пересоздание БД (удалит данные!)
docker-compose down -v && docker-compose up -d
```

### Google Sheets
```bash
# Проверка credentials
docker-compose exec app ls -la /app/config/creds.json

# Тест синхронизации
docker-compose exec app python -c "
from src.core.sync.data_syncer import data_syncer
import asyncio
asyncio.run(data_syncer.sync_data())
"
```

### Очистка Docker
```bash
# Удаление неиспользуемых образов
docker image prune -f

# Полная очистка
docker system prune -a -f
```

## Безопасность

1. Смените пароли в `src/config/.env`
2. Ограничьте доступ к порту 5432
3. Регулярно обновляйте образы Docker
4. Настройте файрвол

---

**Структура конфигурации:**
```
src/config/
├── .env              # Основная конфигурация
├── .env.example      # Шаблон
└── creds.json        # Google Sheets API