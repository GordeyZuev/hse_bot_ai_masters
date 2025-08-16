"""
Основной файл телеграм бота HSE.
"""
import asyncio
from contextlib import asynccontextmanager
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from src.utils import bot_logger, main_logger, settings
from src.db import create_tables, db_manager
from .handlers import register_handlers
from .middlewares import register_middlewares
from .scheduler import setup_scheduler


class HSEBot:
    """Основной класс телеграм бота HSE."""
    
    def __init__(self):
        self.bot = None
        self.dp = None
        self.scheduler = None
        self.logger = main_logger
    
    async def create_bot(self) -> Bot:
        """Создает экземпляр бота."""
        if not self.bot:
            self.bot = Bot(
                token=settings.bot_token,
                default=DefaultBotProperties(
                    parse_mode=ParseMode.HTML,
                    link_preview_is_disabled=True
                )
            )
            self.logger.info("Bot instance created")
        return self.bot
    
    async def create_dispatcher(self) -> Dispatcher:
        """Создает диспетчер с настройками."""
        if not self.dp:
            # Используем MemoryStorage для FSM (можно заменить на RedisStorage)
            storage = MemoryStorage()
            self.dp = Dispatcher(storage=storage)
            
            # Регистрируем middleware
            register_middlewares(self.dp)
            
            # Регистрируем хендлеры
            register_handlers(self.dp)
            
            self.logger.info("Dispatcher created and configured")
        return self.dp
    
    async def setup_database(self):
        """Настраивает базу данных."""
        try:
            # Проверяем подключение к БД
            if await db_manager.health_check():
                self.logger.info("Database connection successful")
            else:
                self.logger.error("Database connection failed")
                raise Exception("Cannot connect to database")
            
            # Создаем таблицы если их нет
            await create_tables()
            self.logger.info("Database tables created/verified")
            
        except Exception as e:
            self.logger.error(f"Database setup failed: {e}")
            raise
    
    async def setup_scheduler(self):
        """Настраивает планировщик задач."""
        try:
            self.scheduler = await setup_scheduler(self.bot)
            self.logger.info("Scheduler setup completed")
        except Exception as e:
            self.logger.error(f"Scheduler setup failed: {e}")
            raise
    
    async def start_polling(self):
        """Запускает бота в режиме polling."""
        try:
            bot = await self.create_bot()
            dp = await self.create_dispatcher()
            
            # Настраиваем базу данных
            await self.setup_database()
            
            # Настраиваем планировщик
            await self.setup_scheduler()
            
            # Получаем информацию о боте
            bot_info = await bot.get_me()
            self.logger.info(f"Bot started: @{bot_info.username} ({bot_info.full_name})")
            
            # Запускаем polling
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
            
        except Exception as e:
            self.logger.error(f"Error starting bot: {e}")
            raise
        finally:
            await self.cleanup()
    
    async def start_webhook(self, webhook_url: str, webhook_path: str = "/webhook"):
        """Запускает бота в режиме webhook."""
        try:
            bot = await self.create_bot()
            dp = await self.create_dispatcher()
            
            # Настраиваем базу данных
            await self.setup_database()
            
            # Настраиваем планировщик
            await self.setup_scheduler()
            
            # Устанавливаем webhook
            await bot.set_webhook(
                url=f"{webhook_url}{webhook_path}",
                allowed_updates=dp.resolve_used_update_types()
            )
            
            bot_info = await bot.get_me()
            self.logger.info(f"Bot started with webhook: @{bot_info.username} ({bot_info.full_name})")
            self.logger.info(f"Webhook URL: {webhook_url}{webhook_path}")
            
        except Exception as e:
            self.logger.error(f"Error starting bot with webhook: {e}")
            raise
    
    async def cleanup(self):
        """Очищает ресурсы при завершении работы."""
        try:
            if self.scheduler:
                self.scheduler.shutdown()
                self.logger.info("Scheduler stopped")
            
            if self.bot:
                await self.bot.session.close()
                self.logger.info("Bot session closed")
            
            await db_manager.close()
            self.logger.info("Database connection closed")
            
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")


# Глобальный экземпляр бота
hse_bot = HSEBot()


async def main():
    """Основная функция запуска бота."""
    try:
        main_logger.info("Starting HSE Bot...")
        
        if settings.webhook_url:
            # Запуск в режиме webhook
            await hse_bot.start_webhook(
                webhook_url=settings.webhook_url,
                webhook_path=settings.webhook_path
            )
        else:
            # Запуск в режиме polling
            await hse_bot.start_polling()
            
    except KeyboardInterrupt:
        main_logger.info("Bot stopped by user")
    except Exception as e:
        main_logger.error(f"Critical error: {e}")
        raise
    finally:
        await hse_bot.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        main_logger.info("Application terminated by user")
    except Exception as e:
        main_logger.critical(f"Application crashed: {e}")