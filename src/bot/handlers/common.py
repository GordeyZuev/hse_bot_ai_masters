"""
Общие хендлеры для обработки различных типов сообщений.
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

from src.utils import bot_logger


router = Router()


@router.message()
async def unknown_message_handler(message: Message):
    """
    Обработчик неизвестных сообщений.
    Срабатывает для всех сообщений, которые не обработались другими хендлерами.
    """
    user = message.from_user
    
    try:
        response_text = (
            "🤔 Я не понимаю эту команду.\n\n"
            "Используйте /help для просмотра доступных команд или "
            "воспользуйтесь кнопками в меню."
        )
        
        await message.answer(response_text)
        
        bot_logger.user_action(
            user_id=user.id,
            action="unknown_message",
            message_text=message.text[:100] if message.text else "non_text_message",
            username=user.username
        )
        
    except Exception as e:
        bot_logger.error(f"Error in unknown message handler: {e}", user_id=user.id)


@router.callback_query()
async def unknown_callback_handler(callback: CallbackQuery):
    """
    Обработчик неизвестных callback запросов.
    Срабатывает для всех callback, которые не обработались другими хендлерами.
    """
    user = callback.from_user
    
    try:
        await callback.answer("❌ Неизвестная команда или устаревшая кнопка")
        
        bot_logger.user_action(
            user_id=user.id,
            action="unknown_callback",
            callback_data=callback.data,
            username=user.username
        )
        
    except Exception as e:
        bot_logger.error(f"Error in unknown callback handler: {e}", user_id=user.id)


def register_common_handlers(dp):
    """Регистрирует общие хендлеры."""
    dp.include_router(router)