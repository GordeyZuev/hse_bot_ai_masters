from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.utils import get_logger

logger = get_logger()
router = Router()

@router.message(CommandStart())
async def cmd_start(message: Message, db_user):
    """Обработчик команды /start"""
    try:
        user_name = db_user.first_name or "Пользователь"
        
        text = f"""
🎓 <b>Добро пожаловать в HSE Bot, {user_name}!</b>

Этот бот поможет вам отслеживать дедлайны по предметам магистратуры ВШЭ.

<b>Основные команды:</b>
• /help - подробная справка
• /sub - подписаться на предмет
• /mysubs - мои подписки
• /deadlines - ближайшие дедлайны
• /settings - настройки уведомлений

Начните с команды /sub для подписки на интересующие предметы!
        """
        
        # Создаем клавиатуру с быстрыми действиями
        builder = InlineKeyboardBuilder()
        builder.button(text="📚 Подписки", callback_data="quick_sub")
        builder.button(text="📅 Ближайшие дедлайны", callback_data="quick_deadlines")
        builder.button(text="ℹ️ Помощь", callback_data="quick_help")
        builder.adjust(1)
        
        await message.answer(
            text.strip(),
            reply_markup=builder.as_markup()
        )
        
        logger.info(f"Пользователь {db_user.tg_user_id} выполнил команду /start")
        
    except Exception as e:
        logger.error(f"Ошибка в обработчике /start: {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")

def register_start_handlers(dp):
    """Регистрация handlers для команды start"""
    dp.include_router(router)