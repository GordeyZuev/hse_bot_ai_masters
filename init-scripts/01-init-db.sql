-- Инициализация базы данных HSE Bot
-- Этот скрипт выполняется автоматически при первом запуске PostgreSQL контейнера

-- Установка пароля для суперпользователя postgres (если еще не установлен)
-- Это необходимо для миграций Alembic
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_shadow WHERE usename = 'postgres' AND passwd IS NOT NULL) THEN
        -- Пароль будет установлен через переменную окружения при первом запуске
        NULL;
    END IF;
END $$;

-- Создание расширений
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Установка временной зоны (унифицировано на UTC)
SET timezone = 'UTC';

-- Выдача прав на схему public для всех пользователей
-- Это необходимо для работы с PostgreSQL 15+, где права по умолчанию ограничены
GRANT ALL ON SCHEMA public TO public;

-- Выдача прав на будущие таблицы для текущего пользователя и postgres
-- Это позволяет миграциям работать от имени postgres
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO postgres, current_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO postgres, current_user;

-- Выдача прав на все существующие таблицы текущему пользователю (если таблицы уже созданы)
-- Это необходимо, если база данных была создана с другим пользователем
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
        EXECUTE 'GRANT ALL ON TABLE public.' || quote_ident(r.tablename) || ' TO current_user';
    END LOOP;
    
    FOR r IN (SELECT sequence_name FROM information_schema.sequences WHERE sequence_schema = 'public') LOOP
        EXECUTE 'GRANT ALL ON SEQUENCE public.' || quote_ident(r.sequence_name) || ' TO current_user';
    END LOOP;
END $$;

-- Логирование успешной инициализации
\echo 'Database initialization completed successfully'