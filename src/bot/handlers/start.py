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
🎓 <b>Добро пожаловать в Бота-оповещателя, {user_name}!</b>

Этот бот поможет вам отслеживать дедлайны по предметам магистратуры «Искусственный Интеллект» (НИУ ВШЭ).

<b>Рекомендуем пользоваться кнопками.</b> 
Описание бота и функционал в виде команд можно найти в разделе «Помощь».
        """
        
        builder = InlineKeyboardBuilder()
        builder.button(text="📚 Подписки", callback_data="quick_sub")
        builder.button(text="📅 Дедлайны", callback_data="quick_deadlines")
        builder.button(text="⚙️ Настройки", callback_data="quick_settings")
        builder.button(text="ℹ️ Помощь", callback_data="quick_help")
        
        from src.bot.handlers.admin import is_admin
        
        if is_admin(db_user.tg_user_id):
            builder.row()
            builder.button(text="👨‍💼 Админ-панель", callback_data="admin_panel")
            builder.adjust(2, 2, 1)
        else:
            builder.adjust(2, 2)
        
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