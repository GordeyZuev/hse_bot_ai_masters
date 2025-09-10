import os
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.bot.handlers.admin import is_admin
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
    await send_help_message(callback.message, db_user, edit_mode=True)

async def send_help_message(message: Message, db_user, edit_mode: bool = False):
    """Отправка сообщения с помощью"""
    try:
        fcs_wiki_url = os.getenv('FCS_WIKI_URL', 'https://wiki.cs.hse.ru')
        google_sheets_url = os.getenv('GOOGLE_SHEETS_URL', 'https://docs.google.com/spreadsheets')
        
        text = f"""
📖 <b>Подробная справка по боту</b>

🔗 <a href="{fcs_wiki_url}">ФКН Вики - страничка программы</a>
📊 <a href="{google_sheets_url}">Табличка с дедлайнами</a>

<b>🎯 Основные команды:</b>

<b>📚 Управление подписками:</b>
• /sub - подписаться на предметы
• /unsub - отписаться от предмета
• /unsuball - отписаться от всех предметов
• /mysubs - показать мои подписки

<b>📅 Дедлайны:</b>
• /deadlines N - дедлайны в ближайшие N дней (N = 15 по умолчанию)

<b>⚙️ Настройки:</b>
• /settings - настройки уведомлений

<b>ℹ️ Информация:</b>
• /start - главное меню
• /help - эта справка

<b>🔔 Уведомления:</b>
Бот автоматически присылает уведомления о приближающихся дедлайнах.
Настроить время и частоту уведомлений можно в /settings.
        """ + ("""
<b>📊 Для администраторов:</b>
• /stats - статистика использования и админ-панель
• /fast_sync - быстрая синхронизация с Google Sheets
• /broadcast - массовая рассылка
• /logs - получить файлы логов
""" if is_admin(db_user.tg_user_id) else "") + """
<b>💡 Совет:</b> Начните с подписок на предметы!
        """
        
        # Создаем клавиатуру с полезными действиями
        builder = InlineKeyboardBuilder()
        builder.button(text="📚 Подписки", callback_data="quick_sub")
        builder.button(text="📅 Дедлайны", callback_data="quick_deadlines")
        builder.button(text="⚙️ Настройки", callback_data="quick_settings")
        builder.button(text="🔙 Назад", callback_data="back_to_menu")
        builder.adjust(2, 2)  # 2 кнопки в первом ряду, 2 во втором
        
        if edit_mode:
            await message.edit_text(
                text.strip(),
                reply_markup=builder.as_markup()
            )
        else:
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