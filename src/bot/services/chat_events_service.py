"""
Обработчики событий чатов

Этот модуль содержит обработчики для отслеживания изменений статуса бота в чатах:
- Добавление/удаление бота из чатов
- Деактивация/активация чатов
"""

from aiogram import Router
from aiogram.types import ChatMemberUpdated

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
            await handle_bot_added_to_chat(chat_id, chat_title, new_status)

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


async def handle_bot_added_to_chat(chat_id: int, chat_title: str, new_status: str):
    """Обработка добавления бота в чат"""
    try:
        # Получаем чат из базы данных
        chat_group = await chat_service.get_chat_group(chat_id)

        if chat_group:
            # Если чат был деактивирован при удалении, активируем его обратно
            if not chat_group.is_active:
                await chat_service.activate_chat(chat_id)
                logger.info(f"(C) {chat_id} - Добавлен обратно, активирован")
            else:
                logger.info(f"(C) {chat_id} - Добавлен в активный чат")
        else:
            logger.info(f"(C) {chat_id} - Добавлен в новый чат (не настроен)")

    except Exception as e:
        logger.error(f"(C) {chat_id} - Ошибка добавления: {e}")


def register_chat_events_handlers(dp):
    """Регистрация обработчиков событий чатов"""
    dp.include_router(router)
