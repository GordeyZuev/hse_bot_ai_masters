-- Инициализация базы данных HSE Bot
-- Этот скрипт выполняется автоматически при первом запуске PostgreSQL контейнера

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

-- Логирование успешной инициализации
\echo 'Database initialization completed successfully'