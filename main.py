import asyncio
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent))

from src.bot.bot import hse_bot
from src.core.database import db_manager
from src.core.scheduler import hse_scheduler
from src.core.sync.data_syncer import data_syncer
from src.utils import get_logger


logger = get_logger()


class HSEBotSyncApp:
    """Основное приложение для синхронизации данных"""

    def __init__(self):
        self.scheduler = hse_scheduler
        self.db_manager = db_manager
        self.data_syncer = data_syncer

    async def initialize(self):
        """Инициализация приложения"""
        await self.db_manager.ensure_initialized()
        # Сначала синхронизируем дисциплины, затем дедлайны
        try:
            await self.data_syncer.sync_subjects()
        except Exception as e:
            logger.warning(f"Инициализация: ошибка синхронизации дисциплин: {e}")
        success = await self.data_syncer.sync_data()

        if success:
            logger.info("Инициализация завершена успешно")
        else:
            logger.warning("Инициализация завершена с предупреждениями")

        return True

    async def start_sync_scheduler(self):
        """Запуск планировщика синхронизации"""
        try:
            self.scheduler.add_sync_job(1)  # Каждый час
            self.scheduler.add_daily_cleanup_job(5, 0)  # Очистка в 5:00
            self.scheduler.start()

            logger.info("Планировщик запущен. Для остановки нажмите Ctrl+C")
            while self.scheduler.is_running:
                await asyncio.sleep(1)

        except KeyboardInterrupt:
            logger.info("Получен сигнал прерывания")
        finally:
            await self.shutdown()

    async def run_single_sync(self):
        """Выполнить одну синхронизацию и завершить работу"""
        try:
            success = await self.data_syncer.sync_data()
            return success
        finally:
            await self.shutdown()

    async def shutdown(self):
        """Корректное завершение работы приложения"""
        if self.scheduler.is_running:
            self.scheduler.stop()
        await self.db_manager.close()


async def run_migrations():
    """Запуск миграций базы данных через программный API Alembic"""
    try:
        logger.info("Запуск миграций базы данных...")

        # Импортируем Alembic API
        from alembic.command import upgrade
        from alembic.script import ScriptDirectory

        from alembic import config as alembic_config

        # Получаем URL базы данных из db_manager
        # Alembic работает с синхронными соединениями, поэтому убираем +asyncpg
        database_url = db_manager.database_url.replace("+asyncpg", "")

        # Создаем конфигурацию Alembic
        alembic_cfg = alembic_config.Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", database_url)

        # Инициализируем скрипт-директорию для проверки версий
        script_dir = ScriptDirectory.from_config(alembic_cfg)
        head_rev = script_dir.get_current_head()

        # Создаем синхронный движок для Alembic
        from sqlalchemy import create_engine
        sync_engine = create_engine(database_url, pool_pre_ping=True)

        try:
            # Проверяем текущую версию
            from alembic.runtime.migration import MigrationContext
            with sync_engine.connect() as sync_conn:
                context = MigrationContext.configure(sync_conn)
                current_rev = context.get_current_revision()

                if current_rev == head_rev:
                    logger.info(f"База данных уже на актуальной версии: {head_rev}")
                    return True

                logger.info(f"Текущая версия: {current_rev}, целевая версия: {head_rev}")

            # Выполняем миграции
            # upgrade принимает только config и revision, connection берется из config
            upgrade(alembic_cfg, "head")

            logger.info("Миграции выполнены успешно")
            return True

        finally:
            sync_engine.dispose()

    except Exception as e:
        logger.error(f"Ошибка запуска миграций: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


async def restore_database():
    """Восстановление базы данных через SQLAlchemy"""
    try:
        logger.info("Восстановление структуры базы данных...")

        await db_manager.initialize(recreate_tables=True)

        logger.info("База данных успешно восстановлена!")
        return True

    except Exception as e:
        logger.error(f"Ошибка восстановления базы данных: {e}")
        return False


async def main():
    """Основная функция приложения"""
    command = sys.argv[1].lower() if len(sys.argv) > 1 else "help"

    if command == "sync":
        logger.info("Режим: одиночная синхронизация")
        app = HSEBotSyncApp()
        await app.initialize()
        success = await app.run_single_sync()
        sys.exit(0 if success else 1)

    elif command == "scheduler":
        logger.info("Режим: планировщик синхронизации")
        app = HSEBotSyncApp()
        await app.initialize()
        await app.start_sync_scheduler()

    elif command == "bot":
        logger.info("Режим: только телеграм бот")
        await hse_bot.start_polling(with_scheduler=False)

    elif command == "full":
        logger.info("Режим: бот + синхронизация + уведомления")
        await hse_bot.start_polling(with_scheduler=True)

    elif command == "migrate":
        logger.info("Режим: выполнение миграций")
        success = await run_migrations()
        sys.exit(0 if success else 1)

    elif command == "restore":
        logger.info("Режим: восстановление базы данных")
        success = await restore_database()
        sys.exit(0 if success else 1)

    else:
        print("Телеграм бот для уведомлений о дедлайнах")
        print()
        print("Использование:")
        print("  uv run python main.py bot       - запустить только телеграм бота")
        print("  uv run python main.py sync      - выполнить одну синхронизацию")
        print("  uv run python main.py scheduler - запустить только планировщик синхронизации")
        print("  uv run python main.py full      - запустить бота + синхронизацию")
        print("  uv run python main.py migrate   - выполнить миграции базы данных")
        print("  uv run python main.py restore   - восстановить структуру базы данных")
        print("  uv run python main.py help      - показать эту справку")
        print()
        print("Рекомендуется использовать 'full' для полного функционала.")
        print("Или используйте 'make run' для удобного запуска.")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Программа завершена пользователем")
    except Exception as e:
        logger.critical(f"Критическая ошибка: {e}")
        sys.exit(1)
