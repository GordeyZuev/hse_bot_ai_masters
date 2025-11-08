import os

from aiogram import F, Router
from aiogram.filters import Command, and_f
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.bot.handlers.admin import is_admin
from src.bot.texts import ADMIN_HELP_TEXT, ERROR_NO_PERMISSION, HELP_TEXT
from src.utils import get_logger, safe_edit_message


logger = get_logger()
router = Router()


@router.message(and_f(Command("help"), F.chat.type == "private"))
async def cmd_help(message: Message, db_user):
    """Обработчик команды /help для личных сообщений"""
    await send_help_message(message, db_user)


@router.callback_query(F.data == "quick_help")
async def callback_help(callback: CallbackQuery, db_user):
    """Обработчик кнопки помощи"""
    # Проверяем, вызвана ли кнопка в групповом чате
    if callback.message.chat.type in ["group", "supergroup"]:
        # Логируем действие в чате
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        chat_title = callback.message.chat.title or f"Чат {chat_id}"
        username = callback.from_user.username

        logger.info(f"[CHAT] quick_help в чате '{chat_title}' (ID: {chat_id}) пользователем @{username or f'ID{user_id}'}")

        # Только админам показываем справку в чате
        from src.bot.services.chat_service import chat_service
        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.answer(ERROR_NO_PERMISSION, show_alert=True)
            return

        await callback.answer()

        # Перенаправляем в group_chat.py
        from src.bot.handlers.group_chat import send_chat_help_message
        await send_chat_help_message(callback.message, edit_mode=True)
    else:
        await callback.answer()
        # Для личных сообщений обрабатываем здесь
        await send_help_message(callback.message, db_user, edit_mode=True)


async def send_help_message(message: Message, db_user, edit_mode: bool = False):
    """Отправка сообщения с помощью"""
    try:
        fcs_wiki_url = os.getenv("FCS_WIKI_URL", "https://wiki.cs.hse.ru")

        text = HELP_TEXT.format(fcs_wiki_url=fcs_wiki_url)
        if is_admin(db_user.tg_user_id):
            text += ADMIN_HELP_TEXT

        # Создаем клавиатуру с полезными действиями
        builder = InlineKeyboardBuilder()
        builder.button(text="📚 Подписки", callback_data="quick_sub")
        builder.button(text="📅 Дедлайны", callback_data="quick_deadlines")
        builder.button(text="⚙️ Настройки", callback_data="quick_settings")
        builder.button(text="🔙 Назад", callback_data="back_to_menu")
        builder.adjust(1)

        if edit_mode:
            await safe_edit_message(
                message, text,
                reply_markup=builder.as_markup(),
                disable_web_page_preview=True,
            )
        else:
            await message.answer(
                text,
                reply_markup=builder.as_markup(),
                disable_web_page_preview=True,
            )

        logger.info(f"(U) {db_user.tg_user_id} - Помощь")

    except Exception as e:
        user_id = message.from_user.id if message.from_user else 0
        logger.error(f"(U) {user_id} - команда /help: {e}")
        from src.bot.texts import ERROR_COMMAND_HELP
        await message.answer(ERROR_COMMAND_HELP)


def register_help_handlers(dp):
    """Регистрация handlers для команды help"""
    dp.include_router(router)
