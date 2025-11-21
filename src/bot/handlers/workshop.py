from aiogram import F, Router
from aiogram.filters import Command, and_f
from aiogram.types import Message

from src.bot.texts import ERROR_COMMAND_WORKSHOP, WORKSHOP_TEXT
from src.utils import get_logger


logger = get_logger()
router = Router()


@router.message(and_f(Command("workshop"), F.chat.type == "private"))
async def cmd_workshop(message: Message, db_user):
    """Обработчик команды /workshop для личных сообщений"""
    try:
        await message.answer(
            WORKSHOP_TEXT,
            disable_web_page_preview=True,
        )
        logger.info(f"(U) {db_user.tg_user_id} - /workshop")

    except Exception as e:
        user_id = message.from_user.id if message.from_user else 0
        logger.error(f"(U) {user_id} - команда /workshop: {e}")
        await message.answer(ERROR_COMMAND_WORKSHOP)


def register_workshop_handlers(dp):
    """Регистрация handlers для команды workshop"""
    dp.include_router(router)

