"""
Хендлеры для команды /start и регистрации пользователей.
"""
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.db import UserCRUD, NotificationSettingsCRUD, get_db_session
from src.utils import bot_logger


router = Router()


@router.message(CommandStart())
async def start_handler(message: Message):
    """
    Обработчик команды /start.
    Регистрирует нового пользователя или приветствует существующего.
    """
    user = message.from_user
    
    try:
        async with get_db_session() as session:
            # Получаем или создаем пользователя
            db_user, created = await UserCRUD.get_or_create(
                session=session,
                telegram_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                language_code=user.language_code or "ru"
            )
            
            # Создаем настройки уведомлений для нового пользователя
            if created:
                await NotificationSettingsCRUD.get_or_create(session, db_user.id)
                bot_logger.user_action(
                    user_id=user.id,
                    action="user_registered",
                    username=user.username,
                    first_name=user.first_name
                )
            else:
                bot_logger.user_action(
                    user_id=user.id,
                    action="user_returned",
                    username=user.username
                )
        
        # Формируем приветственное сообщение
        if created:
            welcome_text = (
                f"👋 Добро пожаловать, {user.first_name or 'студент'}!\n\n"
                "🎓 Я бот для уведомлений о дедлайнах магистерской программы НИУ ВШЭ.\n\n"
                "📚 <b>Что я умею:</b>\n"
                "• Отправлять уведомления о приближающихся дедлайнах\n"
                "• Управлять подписками на дисциплины\n"
                "• Настраивать время и количество уведомлений\n"
                "• Показывать актуальные задания\n\n"
                "🚀 Для начала выберите дисциплины, на которые хотите подписаться!"
            )
        else:
            welcome_text = (
                f"👋 С возвращением, {user.first_name or 'студент'}!\n\n"
                "🎓 Рад снова вас видеть! Я готов помочь с отслеживанием дедлайнов.\n\n"
                "📋 Используйте команды ниже для управления подписками и настройками."
            )
        
        # Создаем клавиатуру с основными действиями
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="📚 Мои подписки", callback_data="my_subscriptions")
        keyboard.button(text="➕ Подписаться", callback_data="subscribe")
        keyboard.button(text="⚙️ Настройки", callback_data="settings")
        keyboard.button(text="❓ Помощь", callback_data="help")
        keyboard.adjust(2, 2)
        
        await message.answer(
            text=welcome_text,
            reply_markup=keyboard.as_markup()
        )
        
    except Exception as e:
        bot_logger.error(f"Error in start handler: {e}", user_id=user.id)
        await message.answer(
            "😔 Произошла ошибка при регистрации. Попробуйте позже или обратитесь к администратору."
        )


def register_start_handlers(dp):
    """Регистрирует хендлеры для команды /start."""
    dp.include_router(router)