-- Инициализация базы данных HSE Bot
-- Этот скрипт выполняется автоматически при первом запуске PostgreSQL контейнера

-- Создание расширений
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Установка временной зоны
SET timezone = 'Europe/Moscow';

-- Создание пользователя приложения (если нужно)
-- DO $$ 
-- BEGIN
--     IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'hse_bot_user') THEN
--         CREATE ROLE hse_bot_user WITH LOGIN PASSWORD 'secure_password';
--         GRANT CONNECT ON DATABASE hse_bot_db TO hse_bot_user;
--     END IF;
-- END
-- $$;

-- Логирование успешной инициализации
\echo 'Database initialization completed successfully'