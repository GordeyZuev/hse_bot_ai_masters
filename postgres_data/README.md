# PostgreSQL Data Directory

Эта директория содержит данные PostgreSQL для HSE Bot.

## 🔐 Безопасность

- **НЕ добавляйте** эту директорию в git (уже в .gitignore)
- **Создавайте регулярные бэкапы** этой директории
- **Ограничьте права доступа** только для владельца

## 📁 Структура

После первого запуска здесь появятся:
- `base/` - файлы баз данных
- `global/` - глобальные таблицы PostgreSQL  
- `pg_wal/` - журнал транзакций
- `postgresql.conf` - конфигурация
- Другие служебные файлы PostgreSQL

## 💾 Резервное копирование

### Простой способ (копирование директории):
```bash
# Остановите контейнер БД
docker-compose stop db

# Создайте бэкап
cp -r postgres_data postgres_data_backup_$(date +%Y%m%d_%H%M%S)

# Запустите контейнер БД
docker-compose start db
```

### Через PostgreSQL dump:
```bash
# Создание дампа
docker-compose exec db pg_dump -U postgres -d hse_bot_db > backup.sql

# Восстановление из дампа
docker-compose exec -T db psql -U postgres -d hse_bot_db < backup.sql
```

## 🚨 Важные замечания

1. **При удалении этой директории** - все данные будут потеряны
2. **При `docker-compose down -v`** - данные НЕ удалятся (в отличие от обычных volumes)
3. **При переносе сервера** - скопируйте эту директорию целиком
4. **Права доступа** должны быть 700 или 755

## 🔄 Восстановление

Если данные повреждены:
1. Остановите контейнер: `docker-compose stop db`
2. Удалите содержимое: `rm -rf postgres_data/*`
3. Восстановите из бэкапа или запустите заново: `docker-compose up -d db`
