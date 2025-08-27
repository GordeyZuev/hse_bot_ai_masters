import asyncio
import os
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from src.bot.handlers import register_handlers
from src.bot.middlewares import register_middlewares
from src.bot.services.bot_scheduler import bot_scheduler
from src.core.database import db_manager
from src.utils import get_logger

# Загружаем переменные окружения
load_dotenv('src/config/.env')

logger = get_logger()

class HSEBot:
    """Основной класс телеграм бота HSE"""
    
    def __init__(self):
        self.bot_token = os.getenv('BOT_TOKEN')
        if not self.bot_token:
            raise ValueError("BOT_TOKEN не найден в переменных окружения")
        
        # Создаем бота с настройками по умолчанию
        self.bot = Bot(
            token=self.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        
        # Создаем диспетчер с хранилищем состояний
        storage = MemoryStorage()
        self.dp = Dispatcher(storage=storage)
        
        logger.info("Бот инициализирован")
    
    async def setup(self, with_scheduler: bool = False):
        """Настройка бота перед запуском"""
        try:
            # Инициализируем базу данных
            await db_manager.ensure_initialized()
            logger.info("База данных инициализирована")
            
            # Регистрируем middleware
            register_middlewares(self.dp)
            logger.info("Middleware зарегистрированы")
            
            # Регистрируем handlers
            register_handlers(self.dp)
            logger.info("Handlers зарегистрированы")
            
            # Настраиваем планировщик если нужно
            if with_scheduler:
                bot_scheduler.set_bot(self.bot)
                bot_scheduler.add_sync_job(1)  # Синхронизация каждый час
                bot_scheduler.add_notification_job(30)  # Уведомления каждые 30 минут
                bot_scheduler.add_daily_cleanup_job(5, 0)  # Очистка в 5:00
                bot_scheduler.add_immediate_sync()  # Немедленная синхронизация при старте
                bot_scheduler.start() 
                logger.info("Планировщик настроен и запущен")
            
            # Получаем информацию о боте
            bot_info = await self.bot.get_me()
            logger.info(f"Бот запущен: @{bot_info.username}")
            
        except Exception as e:
            logger.error(f"Ошибка настройки бота: {e}")
            raise
    
    async def start_polling(self, with_scheduler: bool = False):
        """Запуск бота в режиме polling"""
        try:
            await self.setup(with_scheduler=with_scheduler)
            logger.info("Запуск polling...")
            await self.dp.start_polling(self.bot)
        except Exception as e:
            logger.error(f"Ошибка запуска бота: {e}")
            raise
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """Корректное завершение работы бота"""
        try:
            # Останавливаем планировщик если он запущен
            if bot_scheduler.is_running:
                bot_scheduler.stop()
                logger.info("Планировщик остановлен")
            
            await self.bot.session.close()
            await db_manager.close()
            logger.info("Бот корректно завершил работу")
        except Exception as e:
            logger.error(f"Ошибка при завершении работы бота: {e}")

# Создаем экземпляр бота
hse_bot = HSEBot()

async def main():
    """Основная функция запуска бота"""
    try:
        await hse_bot.start_polling()
    except KeyboardInterrupt:
        logger.info("Получен сигнал прерывания")
    except Exception as e:
        logger.critical(f"Критическая ошибка: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())