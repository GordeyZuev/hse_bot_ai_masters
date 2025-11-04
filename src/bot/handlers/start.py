from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.bot.texts import START_PRIVATE_TEXT
from src.utils import get_logger


logger = get_logger()
router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, db_user):
    """Обработчик команды /start"""
    try:
        user_name = db_user.first_name or "Пользователь"

        if message.chat.type in ["group", "supergroup"]:
            from src.bot.handlers.group_chat import handle_start_in_group
            await handle_start_in_group(message, db_user, user_name)
        else:
            await handle_start_in_private(message, db_user, user_name)
            logger.info(f"(U) {db_user.tg_user_id} - /start")

    except Exception as e:
        logger.error(f"Ошибка в обработчике /start: {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")


async def handle_start_in_private(message: Message, db_user, user_name: str):
    """Обработка команды /start в личных сообщениях"""
    try:
        text = START_PRIVATE_TEXT.format(user_name=user_name)

        builder = InlineKeyboardBuilder()
        builder.button(text="📖 Дисциплины", callback_data="quick_subjects")
        builder.button(text="📅 Дедлайны", callback_data="quick_deadlines")
        builder.button(text="⚙️ Настройки", callback_data="quick_settings")
        builder.button(text="❓ Помощь", callback_data="quick_help")

        from src.bot.handlers.admin import is_admin

        if is_admin(db_user.tg_user_id):
            builder.row()
            builder.button(text="👨‍💼 Админ-панель", callback_data="admin_panel")
            builder.adjust(2, 2, 1)
        else:
            builder.adjust(2, 2)

        await message.answer(text.strip(), reply_markup=builder.as_markup())

    except Exception as e:
        logger.error(f"Ошибка обработки /start в личных сообщениях: {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")


def register_start_handlers(dp):
    """Регистрация handlers для команды start"""
    dp.include_router(router)
