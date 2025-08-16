"""
Хендлеры для команды /help и справочной информации.
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.utils import bot_logger


router = Router()


@router.message(Command("help"))
async def help_command_handler(message: Message):
    """Обработчик команды /help."""
    await show_help(message)


@router.callback_query(F.data == "help")
async def help_callback_handler(callback: CallbackQuery):
    """Обработчик callback для показа помощи."""
    await show_help(callback.message, callback)


async def show_help(message: Message, callback: CallbackQuery = None):
    """
    Показывает справочную информацию о боте.
    
    Args:
        message: Сообщение пользователя
        callback: Callback query (если вызвано через inline кнопку)
    """
    user = callback.from_user if callback else message.from_user
    
    try:
        help_text = (
            "🤖 <b>Справка по боту HSE Deadlines</b>\n\n"
            
            "📚 <b>Основные команды:</b>\n"
            "/start - Запуск бота и регистрация\n"
            "/help - Показать эту справку\n"
            "/my_subscriptions - Мои подписки\n"
            "/subscribe - Подписаться на дисциплины\n"
            "/settings - Настройки уведомлений\n\n"
            
            "🔔 <b>Уведомления:</b>\n"
            "• Бот отправляет до 2 уведомлений о каждом дедлайне\n"
            "• Первое уведомление - за 24 часа (настраивается)\n"
            "• Второе уведомление - за 2 часа (настраивается)\n"
            "• Можно настроить количество и время уведомлений\n\n"
            
            "📋 <b>Подписки:</b>\n"
            "• Подпишитесь на интересующие дисциплины\n"
            "• Получайте уведомления только по выбранным предметам\n"
            "• Управляйте подписками в любое время\n\n"
            
            "⚙️ <b>Настройки:</b>\n"
            "• Количество уведомлений (1 или 2)\n"
            "• Время первого уведомления\n"
            "• Время второго уведомления\n"
            "• Включение/выключение уведомлений\n\n"
            
            "📊 <b>Источник данных:</b>\n"
            "Информация о дедлайнах берется из официальной Google таблицы "
            "магистерской программы и обновляется автоматически.\n\n"
            
            "❓ <b>Проблемы?</b>\n"
            "Если возникли вопросы или проблемы, обратитесь к администратору программы."
        )
        
        # Создаем клавиатуру с полезными действиями
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="📚 Мои подписки", callback_data="my_subscriptions")
        keyboard.button(text="➕ Подписаться", callback_data="subscribe")
        keyboard.button(text="⚙️ Настройки", callback_data="settings")
        keyboard.button(text="🏠 Главное меню", callback_data="main_menu")
        keyboard.adjust(2, 2)
        
        if callback:
            await callback.message.edit_text(
                text=help_text,
                reply_markup=keyboard.as_markup()
            )
            await callback.answer()
        else:
            await message.answer(
                text=help_text,
                reply_markup=keyboard.as_markup()
            )
        
        bot_logger.user_action(
            user_id=user.id,
            action="help_viewed",
            username=user.username
        )
        
    except Exception as e:
        bot_logger.error(f"Error in help handler: {e}", user_id=user.id)
        error_text = "😔 Произошла ошибка при загрузке справки. Попробуйте позже."
        
        if callback:
            await callback.message.edit_text(error_text)
            await callback.answer("Ошибка при загрузке справки")
        else:
            await message.answer(error_text)


@router.callback_query(F.data == "main_menu")
async def main_menu_handler(callback: CallbackQuery):
    """Обработчик возврата в главное меню."""
    user = callback.from_user
    
    try:
        main_menu_text = (
            f"🏠 <b>Главное меню</b>\n\n"
            f"Привет, {user.first_name or 'студент'}! 👋\n\n"
            "Выберите действие:"
        )
        
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="📚 Мои подписки", callback_data="my_subscriptions")
        keyboard.button(text="➕ Подписаться", callback_data="subscribe")
        keyboard.button(text="⚙️ Настройки", callback_data="settings")
        keyboard.button(text="❓ Помощь", callback_data="help")
        keyboard.adjust(2, 2)
        
        await callback.message.edit_text(
            text=main_menu_text,
            reply_markup=keyboard.as_markup()
        )
        await callback.answer()
        
        bot_logger.user_action(
            user_id=user.id,
            action="main_menu_viewed",
            username=user.username
        )
        
    except Exception as e:
        bot_logger.error(f"Error in main menu handler: {e}", user_id=user.id)
        await callback.answer("Ошибка при загрузке главного меню")


def register_help_handlers(dp):
    """Регистрирует хендлеры для справки."""
    dp.include_router(router)