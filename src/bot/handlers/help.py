from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.utils import get_logger

logger = get_logger()
router = Router()

@router.message(Command("help"))
async def cmd_help(message: Message, db_user):
    """Обработчик команды /help"""
    await send_help_message(message, db_user)

@router.callback_query(F.data == "quick_help")
async def callback_help(callback: CallbackQuery, db_user):
    """Обработчик кнопки помощи"""
    await callback.answer()
    await send_help_message(callback.message, db_user)

async def send_help_message(message: Message, db_user):
    """Отправка сообщения с помощью"""
    try:
        text = """
📖 <b>Подробная справка по HSE Bot</b>

<b>🎯 Основные команды:</b>

<b>📚 Управление подписками:</b>
• /sub - подписаться на предметы
• /unsub - отписаться от предмета
• /unsuball - отписаться от всех предметов
• /mysubs - показать мои подписки

<b>📅 Дедлайны:</b>
• /deadlines - ближайшие дедлайны (15 дней)
• /deadlines 7 - дедлайны на 7 дней
• /deadlines 30 - дедлайны на 30 дней

<b>⚙️ Настройки:</b>
• /settings - настройки уведомлений

<b>ℹ️ Информация:</b>
• /start - главное меню
• /help - эта справка

<b>🔔 Уведомления:</b>
Бот автоматически присылает уведомления о приближающихся дедлайнах. 
Настроить время и частоту уведомлений можно в /settings.

<b>📊 Для администраторов:</b>
• /stats - статистика использования
• /broadcast - массовая рассылка

<b>💡 Совет:</b> Начните с команды /sub для подписки на нужные предметы!
        """
        
        # Создаем клавиатуру с полезными действиями
        builder = InlineKeyboardBuilder()
        builder.button(text="📚 Подписки", callback_data="quick_sub")
        builder.button(text="📅 Дедлайны", callback_data="quick_deadlines")
        builder.button(text="⚙️ Настройки", callback_data="quick_settings")
        builder.adjust(2, 1)
        
        await message.answer(
            text.strip(),
            reply_markup=builder.as_markup()
        )
        
        logger.info(f"Пользователь {db_user.tg_user_id} запросил помощь")
        
    except Exception as e:
        logger.error(f"Ошибка в обработчике /help: {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")

def register_help_handlers(dp):
    """Регистрация handlers для команды help"""
    dp.include_router(router)