-- Инициализация базы данных HSE Bot
-- Этот скрипт выполняется автоматически при первом запуске PostgreSQL контейнера

-- Создание расширений
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Установка временной зоны (унифицировано на UTC)
SET timezone = 'UTC';

-- Выдача прав на схему public для всех пользователей
-- Это необходимо для работы с PostgreSQL 15+, где права по умолчанию ограничены
GRANT ALL ON SCHEMA public TO public;
ALTER SCHEMA public OWNER TO postgres;

-- Логирование успешной инициализации
\echo 'Database initialization completed successfully'