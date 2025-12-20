# 🔄 Обновление revision ID в миграциях Alembic

## ⚠️ Важно!

После изменения revision ID во всех миграциях необходимо обновить таблицу `alembic_version` на сервере, чтобы Alembic мог правильно определить текущую версию базы данных.

## 📋 Маппинг старых → новых revision ID

| Старый revision ID | Новый revision ID | Миграция |
|-------------------|-------------------|----------|
| `001` | `001` | initial_migration |
| `002` | `002` | scheduled_notifications |
| `4f17dc3b1c48` | `003` | remove_outdated_tables |
| `d6117a9653ff` | `004` | add_chat_groups_support |
| `73c1f2a1` | `005` | add_subject_links_and_sheet_id |
| `73b82a745d6e` | `006` | add_is_active_to_users |
| `a1b2c3d4e5f6` | `007` | add_topic_title_to_chat_groups |
| `4d64b6231a53` | `008` | merge_heads |
| `cbea2120eaa8` | `009` | merge_heads_2 |
| `add_notification_updates` | `010` | add_notification_settings |
| `936938f0c3a2` | `011` | add_chat_title |
| `e3f1a2b4c5d6` | `012` | add_task_user_status |
| `f1a2b3c4d5e6` | `013` | rename_deadlines_to_tasks |
| `b93b504740b8` | `014` | refactor_chat_groups |

## 🚀 Инструкция по обновлению на сервере

### 1. Проверьте текущую версию в базе данных

Подключитесь к базе данных на сервере:

```bash
# Через Docker
docker-compose exec db psql -U postgres -d hse_bot_db

# Или через Makefile
make db
```

Выполните SQL запрос для проверки текущей версии:

```sql
SELECT version_num FROM alembic_version;
```

### 2. Определите новый revision ID

Используйте таблицу маппинга выше, чтобы найти новый revision ID, соответствующий старому.

**Пример:**
- Если текущая версия: `b93b504740b8` → новый revision ID: `014`
- Если текущая версия: `f1a2b3c4d5e6` → новый revision ID: `013`

### 3. Обновите таблицу alembic_version

**⚠️ ВАЖНО: Сначала сделайте бэкап базы данных!**

```bash
# Создание бэкапа
./scripts/backup-db.sh
```

Затем обновите версию в таблице:

```sql
-- Замените 'СТАРЫЙ_REVISION_ID' на текущий revision ID из шага 1
-- Замените 'НОВЫЙ_REVISION_ID' на соответствующий новый revision ID из таблицы маппинга

UPDATE alembic_version 
SET version_num = 'НОВЫЙ_REVISION_ID' 
WHERE version_num = 'СТАРЫЙ_REVISION_ID';

-- Проверьте результат
SELECT version_num FROM alembic_version;
```

**Примеры:**

```sql
-- Если текущая версия b93b504740b8 → обновить на 014
UPDATE alembic_version SET version_num = '014' WHERE version_num = 'b93b504740b8';

-- Если текущая версия f1a2b3c4d5e6 → обновить на 013
UPDATE alembic_version SET version_num = '013' WHERE version_num = 'f1a2b3c4d5e6';

-- Если текущая версия add_notification_updates → обновить на 010
UPDATE alembic_version SET version_num = '010' WHERE version_num = 'add_notification_updates';
```

### 4. Проверьте работу миграций

После обновления версии проверьте, что Alembic видит правильную версию:

```bash
# Проверка текущей версии через Alembic
docker-compose exec app alembic current

# Должно показать новый revision ID (например, 014)
```

### 5. Примените обновления (если нужно)

После обновления версии можно безопасно применить новые миграции (если они есть):

```bash
# Применить миграции до head
docker-compose exec app alembic upgrade head

# Или через main.py
docker-compose exec app uv run python main.py migrate
```

## 🔍 Диагностика проблем

### Проблема: Alembic не может найти миграцию

Если вы видите ошибку типа "Can't locate revision identified by 'XXXX'":

1. Проверьте, что вы правильно обновили таблицу `alembic_version`
2. Убедитесь, что все файлы миграций присутствуют в `alembic/versions/`
3. Проверьте, что revision ID в файлах миграций соответствуют новым значениям

### Проблема: Alembic пытается применить уже примененные миграции

Если Alembic пытается применить миграции, которые уже применены:

1. Проверьте текущую версию в таблице `alembic_version`
2. Убедитесь, что она соответствует последней примененной миграции
3. Если версия в таблице меньше, чем последняя примененная миграция, обновите её

### Проверка целостности миграций

Для проверки целостности цепочки миграций:

```bash
# Показать историю миграций
docker-compose exec app alembic history

# Показать текущую версию
docker-compose exec app alembic current
```

## 📝 Примечания

- **Всегда делайте бэкап перед обновлением!**
- Если вы не уверены в текущей версии, сначала проверьте её через `alembic current`
- Если у вас несколько окружений (dev/staging/prod), обновите каждое отдельно
- После обновления проверьте, что приложение работает корректно

## ✅ Чеклист

- [ ] Создан бэкап базы данных
- [ ] Проверена текущая версия в `alembic_version`
- [ ] Определен новый revision ID по таблице маппинга
- [ ] Обновлена таблица `alembic_version`
- [ ] Проверена текущая версия через `alembic current`
- [ ] Проверена работа приложения

