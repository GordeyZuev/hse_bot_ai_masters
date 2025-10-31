import os

from aiogram import F, Router
from aiogram.filters import Command, and_f
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.bot.handlers.admin import is_admin
from src.utils import get_logger


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
            await callback.answer("У вас нет прав для изменения настроек.\nПопросите администратора чата.", show_alert=True)
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

        text = (
            f"""
<b>📖 Справка по боту:</b>
Бот автоматически присылает уведомления о приближающихся дедлайнах. Информация о дедлайнах берется из таблиц в ведомостях.

<b>🔍 Легенда по типам дедлайнов:</b>
• Мягкий дедлайн – 🟡
• Жёсткий дедлайн – 🔴

🔗 <a href="{fcs_wiki_url}">ФКН Вики - страничка программы</a>

<b>🎯 Основные команды:</b>
<blockquote expandable>
<b>📚 Управление подписками:</b>
• /sub — подписаться на предметы.
• /unsub — отписаться от предмета.
• /unsuball — отписаться от всех предметов.
• /mysubs — показать мои подписки.

<b>📅 Дедлайны:</b>
• /deadlines N — дедлайны в ближайшие N дней (по умолчанию N = 15).

<b>⚙️ Настройки:</b>
• /settings — настройки времени уведомлений и часового пояса.

<b>ℹ️ Информация:</b>
• /start — главное меню.
• /help — эта справка.

<b>👥 Для групповых чатов:</b>
• /start — краткое приветствие и ссылки.
• /setup_discipline — выбрать предмет и привязать бота (только для админов).
• /disable_chat — включить/выключить уведомления в чате.

<b>Как настроить бота в чате:</b>
1) Убедитесь, что вы администратор чата.
2) Откройте нужный топик (или останьтесь в общем чате).
3) Вызовите /setup_discipline и выберите предмет.
4) При необходимости привяжите бота к текущему топику (кнопка «Привязать к этому топику» в настройках).
5) Проверьте права бота: рекомендуется «Управление темами форума», чтобы бот мог писать в закрытых темах.
"""
            + (
                """

<b>📊 Для администраторов:</b>
• /stats — статистика использования и админ-панель.
• /fast_sync — быстрая синхронизация с Google Sheets.
• /broadcast — массовая рассылка.
• /logs — получить файлы логов.
• /chat_stats — статистика по чатам.
• /chat_toggle_all — массовое управление чатами.
"""
                if is_admin(db_user.tg_user_id)
                else ""
            )
            + """
</blockquote>

<b>💡 Совет:</b> Начните с подписок на предметы!
        """
        )

        # Создаем клавиатуру с полезными действиями
        builder = InlineKeyboardBuilder()
        builder.button(text="📚 Подписки", callback_data="quick_sub")
        builder.button(text="📅 Дедлайны", callback_data="quick_deadlines")
        builder.button(text="⚙️ Настройки", callback_data="quick_settings")
        builder.button(text="🔙 Назад", callback_data="back_to_menu")
        builder.adjust(1)

        if edit_mode:
            await message.edit_text(
                text.strip(),
                reply_markup=builder.as_markup(),
                disable_web_page_preview=True,
            )
        else:
            await message.answer(
                text.strip(),
                reply_markup=builder.as_markup(),
                disable_web_page_preview=True,
            )

        logger.info(f"(U) {db_user.tg_user_id} - Помощь")

    except Exception as e:
        logger.error(f"Ошибка в обработчике /help: {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")


def register_help_handlers(dp):
    """Регистрация handlers для команды help"""
    dp.include_router(router)
