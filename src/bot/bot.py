import asyncio
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
)
from dotenv import load_dotenv

from src.bot.handlers import register_handlers
from src.bot.middlewares import register_middlewares
from src.bot.services.chat_events_service import register_chat_events_handlers
from src.bot.services.user_events_service import register_user_events_handlers
from src.core.database import db_manager
from src.core.scheduler import hse_scheduler
from src.core.sync.data_syncer import data_syncer
from src.utils import get_logger


load_dotenv("src/config/.env")

logger = get_logger()


class HSEBot:
    """Основной класс телеграм бота HSE"""

    def __init__(self):
        self.bot_token = os.getenv("BOT_TOKEN")
        if not self.bot_token:
            raise ValueError("BOT_TOKEN не найден в переменных окружения")

        proxy = (os.getenv("BOT_PROXY") or "").strip() or None
        self.bot = Bot(
            token=self.bot_token,
            session=AiohttpSession(proxy=proxy) if proxy else None,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )

        storage = MemoryStorage()
        self.dp = Dispatcher(storage=storage)

        logger.info("Бот инициализирован")

    async def setup_commands(self) -> None:
        """Register small, context-aware command menus."""
        await self.bot.set_my_commands(
            [
                BotCommand(command="deadlines", description="Ближайшие дедлайны"),
                BotCommand(command="subjects", description="Дисциплины и подписки"),
                BotCommand(command="settings", description="Настройки"),
                BotCommand(command="help", description="Помощь"),
            ],
            scope=BotCommandScopeAllPrivateChats(),
        )
        await self.bot.set_my_commands(
            [
                BotCommand(command="info", description="Дедлайны группы"),
                BotCommand(command="help", description="Помощь", is_ephemeral=True),
            ],
            scope=BotCommandScopeAllGroupChats(),
        )
        await self.bot.set_my_commands(
            [
                BotCommand(
                    command="setup_discipline",
                    description="Выбрать дисциплину",
                    is_ephemeral=True,
                ),
                BotCommand(
                    command="chat_settings",
                    description="Настройки группы",
                    is_ephemeral=True,
                ),
                BotCommand(command="info", description="Дедлайны группы"),
            ],
            scope=BotCommandScopeAllChatAdministrators(),
        )

    async def setup(self, with_scheduler: bool = False):
        """Настройка бота перед запуском"""
        try:
            await db_manager.ensure_initialized()
            logger.info("База данных инициализирована")

            if not with_scheduler:
                try:
                    await data_syncer.sync_subjects()
                except Exception as e:
                    logger.warning(
                        f"Старт бота: не удалось синхронизировать дисциплины: {e}"
                    )

            register_middlewares(self.dp)
            logger.info("Middleware зарегистрированы")

            register_handlers(self.dp)
            logger.info("Handlers зарегистрированы")

            register_user_events_handlers(self.dp)
            register_chat_events_handlers(self.dp)
            logger.info("Event services зарегистрированы")

            await self.setup_commands()
            logger.info("Контекстные команды зарегистрированы")

            if with_scheduler:
                hse_scheduler.set_bot(self.bot)
                hse_scheduler.add_sync_job(1)
                hse_scheduler.add_notification_job(15)
                hse_scheduler.add_daily_cleanup_job(5, 0)
                hse_scheduler.add_immediate_sync()
                hse_scheduler.start()
                logger.info("Планировщик настроен и запущен")

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
            if hse_scheduler.is_running:
                hse_scheduler.stop()
                logger.info("Планировщик остановлен")

            await self.bot.session.close()
            await db_manager.close()
            logger.info("Бот корректно завершил работу")
        except Exception as e:
            logger.error(f"Ошибка при завершении работы бота: {e}")


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
