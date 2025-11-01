#!/bin/bash
# Выдача прав пользователю на все таблицы

docker exec hse_bot_db psql -U postgres -d hse_bot_db <<'SQL'
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
        EXECUTE 'ALTER TABLE public.' || quote_ident(r.tablename) || ' OWNER TO hse_bot_user';
        EXECUTE 'GRANT ALL ON TABLE public.' || quote_ident(r.tablename) || ' TO hse_bot_user';
    END LOOP;
    FOR r IN (SELECT sequence_name FROM information_schema.sequences WHERE sequence_schema = 'public') LOOP
        EXECUTE 'ALTER SEQUENCE public.' || quote_ident(r.sequence_name) || ' OWNER TO hse_bot_user';
        EXECUTE 'GRANT ALL ON SEQUENCE public.' || quote_ident(r.sequence_name) || ' TO hse_bot_user';
    END LOOP;
    GRANT ALL ON SCHEMA public TO hse_bot_user;
END $$;
SQL

