"""
Обработчики событий чатов

Этот модуль содержит обработчики для отслеживания изменений статуса бота в чатах:
- Добавление/удаление бота из чатов
- Деактивация/активация чатов
"""

from aiogram import Router
from aiogram.types import ChatMemberUpdated
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.bot.services.chat_notification_scheduler_service import (
    chat_notification_scheduler_service,
)
from src.bot.services.chat_service import chat_service
from src.utils import get_logger


logger = get_logger()
router = Router()


@router.my_chat_member()
async def handle_bot_chat_member_update(update: ChatMemberUpdated):
    """Обработчик изменения статуса бота в чате"""
    try:
        chat_id = update.chat.id
        chat_title = update.chat.title or f"Чат {chat_id}"

        old_status = update.old_chat_member.status
        new_status = update.new_chat_member.status

        logger.debug(f"Статус бота в чате '{chat_title}' ({chat_id}): {old_status} → {new_status}")

        # Бот был удален из чата
        if old_status in ["member", "administrator"] and new_status in ["left", "kicked"]:
            await handle_bot_removed_from_chat(chat_id, chat_title, new_status)

        # Бот был добавлен в чат
        elif old_status in ["left", "kicked"] and new_status in ["member", "administrator"]:
            await handle_bot_added_to_chat(update)

    except Exception as e:
        logger.error(f"Ошибка изменения статуса бота в чате: {e}")


async def handle_bot_removed_from_chat(chat_id: int, chat_title: str, removal_status: str):
    """Обработка удаления бота из чата"""
    try:
        # Получаем чат из базы данных
        chat_group = await chat_service.get_chat_group(chat_id)

        if chat_group:
            # Деактивируем чат
            await chat_service.deactivate_chat(chat_id)

            # Отменяем все запланированные уведомления
            cancelled_count = await chat_notification_scheduler_service.cancel_chat_notifications(chat_id)

            logger.info(f"(C) {chat_id} - Удален. Отменено уведомлений: {cancelled_count}")
        else:
            logger.info(f"(C) {chat_id} - Удален из ненастроенного чата")

    except Exception as e:
        logger.error(f"(C) {chat_id} - Ошибка удаления: {e}")


async def handle_bot_added_to_chat(update: ChatMemberUpdated):
    """Обработка добавления бота в чат"""
    try:
        chat_id = update.chat.id
        chat_title = update.chat.title or f"Чат {chat_id}"
        bot = update.bot

        logger.info(f"(C) {chat_id} - Добавлен в чат '{chat_title}'")

        # Получаем чат из базы данных
        chat_group = await chat_service.get_chat_group(chat_id)

        if chat_group:
            # Если чат был деактивирован при удалении, активируем его обратно
            if not chat_group.is_active:
                await chat_service.activate_chat(chat_id)
                logger.info(f"(C) {chat_id} - Активирован обратно")

            # Отправляем приветственное сообщение для уже настроенного чата
            try:
                text = f"""
🤖 <b>Привет!</b>

Чат уже настроен на предмет: <b>«{chat_group.subject.name}»</b>

Статус: {'✅ Активен' if chat_group.is_active else '❌ Отключен'}

💡 Используйте команду /info для просмотра информации о предмете и актуальных дедлайнах.

<i>Все о настройке и возможностях — в разделе помощи.</i>
                """

                builder = InlineKeyboardBuilder()
                builder.button(text="ℹ️ Информация", callback_data="chat_info")
                builder.button(text="⚙️ Настройка бота", callback_data="chat_settings_from_start")
                builder.button(text="❓ Помощь", callback_data="quick_help")
                builder.adjust(1)

                await bot.send_message(
                    chat_id=chat_id,
                    text=text.strip(),
                    reply_markup=builder.as_markup(),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"(C) {chat_id} - Не удалось отправить приветствие: {e}")

        else:
            logger.info(f"(C) {chat_id} - Новый чат (не настроен)")
            
            # Отправляем приветственное сообщение для нового чата
            try:
                text = """
🤖 <b>Привет!</b>

Этот бот помогает отслеживать дедлайны по предметам в этом чате.

<b>Как начать:</b>
1) Убедитесь, что вы администратор чата
2) Нажмите «Настроить бота» ниже
3) Выберите предмет для отслеживания дедлайнов

<b>Совет:</b> Настраивайте бота в нужном топике — тогда напоминания будут приходить только туда.

Подробные инструкции — в разделе помощи.
                """

                builder = InlineKeyboardBuilder()
                builder.button(text="⚙️ Настроить бота", callback_data="chat_setup_from_start")
                builder.button(text="❓ Помощь", callback_data="quick_help")
                builder.adjust(1)

                await bot.send_message(
                    chat_id=chat_id,
                    text=text.strip(),
                    reply_markup=builder.as_markup(),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"(C) {chat_id} - Не удалось отправить приветствие: {e}")

    except Exception as e:
        logger.error(f"(C) {chat_id} - Ошибка добавления: {e}")


def register_chat_events_handlers(dp):
    """Регистрация обработчиков событий чатов"""
    dp.include_router(router)
