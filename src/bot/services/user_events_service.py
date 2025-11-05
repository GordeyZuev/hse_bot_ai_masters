"""
Обработчики событий пользователей

Этот модуль содержит обработчики для отслеживания изменений статуса пользователей:
- Блокировка/разблокировка бота пользователем
- Деактивация/активация пользователей
"""

from aiogram import Router
from aiogram.types import ChatMemberUpdated

from src.core.database import db_manager
from src.utils import get_logger


logger = get_logger()
router = Router()


@router.my_chat_member()
async def handle_user_chat_member_update(update: ChatMemberUpdated):
    """Обработчик изменения статуса бота в личном чате с пользователем"""
    try:
        if update.chat.type != "private":
            return

        user_id = update.chat.id
        old_status = update.old_chat_member.status
        new_status = update.new_chat_member.status

        logger.debug(f"Статус бота в личном чате с пользователем {user_id}: {old_status} → {new_status}")

        # Пользователь заблокировал бота
        if old_status in ["member"] and new_status in ["kicked", "left"]:
            await handle_user_blocked_bot(user_id)

        # Пользователь разблокировал бота
        elif old_status in ["kicked", "left"] and new_status in ["member"]:
            await handle_user_unblocked_bot(user_id)

    except Exception as e:
        logger.error(f"Ошибка изменения статуса пользователя: {e}")


async def handle_user_blocked_bot(user_id: int):
    """Обработка блокировки бота пользователем"""
    try:
        success = await deactivate_user(user_id)

        cancelled_count = await cancel_user_notifications(user_id)

        if success:
            logger.info(f"(U) {user_id} - Заблокировал бота. Отменено уведомлений: {cancelled_count}")
        else:
            logger.info(f"(U) {user_id} - Заблокировал бота (не найден в БД). Отменено уведомлений: {cancelled_count}")

    except Exception as e:
        logger.error(f"(U) {user_id} - Ошибка блокировки: {e}")


async def handle_user_unblocked_bot(user_id: int):
    """Обработка разблокировки бота пользователем"""
    try:
        # Активируем пользователя
        success = await activate_user(user_id)

        if success:
            try:
                from src.bot.services.notification_scheduler_service import (
                    notification_scheduler_service,
                )

                scheduled_count = await notification_scheduler_service.schedule_notifications_for_user_settings_creation(
                    user_id
                )
                logger.info(
                    f"(U) {user_id} - Разблокировал бота, активирован. Запланировано уведомлений: {scheduled_count}"
                )
            except Exception as e:
                logger.warning(
                    f"(U) {user_id} - Разблокировал бота, активирован, но не удалось пересоздать уведомления: {e}"
                )
        else:
            logger.info(f"(U) {user_id} - Разблокировал бота (не найден в БД)")

    except Exception as e:
        logger.error(f"(U) {user_id} - Ошибка разблокировки: {e}")


async def deactivate_user(user_id: int) -> bool:
    """Деактивация пользователя (при блокировке бота)"""
    try:
        async with db_manager.async_session() as session:
            from src.core.models.models import User

            user = await session.get(User, user_id)
            if user:
                user.is_active = False
                await session.commit()
                logger.info(f"(U) {user_id} - Деактивирован")
                return True
            return False
    except Exception as e:
        logger.error(f"(U) {user_id} - Ошибка деактивации: {e}")
        return False


async def activate_user(user_id: int) -> bool:
    """Активация пользователя (при разблокировке бота)"""
    try:
        async with db_manager.async_session() as session:
            from src.core.models.models import User

            user = await session.get(User, user_id)
            if user:
                user.is_active = True
                await session.commit()
                logger.info(f"(U) {user_id} - Активирован")
                return True
            return False
    except Exception as e:
        logger.error(f"(U) {user_id} - Ошибка активации: {e}")
        return False


async def cancel_user_notifications(user_id: int) -> int:
    """Отмена всех запланированных уведомлений пользователя (при блокировке бота)

    Отменяет уведомления со статусами 'scheduled' и 'failed',
    так как при блокировке бота не нужно пытаться отправлять уведомления.
    """
    try:
        async with db_manager.async_session() as session:
            from sqlalchemy import update

            from src.core.models.models import ScheduledNotification

            # Обновляем статус всех запланированных и неудачных уведомлений на 'cancelled'
            result = await session.execute(
                update(ScheduledNotification)
                .where(
                    ScheduledNotification.user_id == user_id,
                    ScheduledNotification.status.in_(["scheduled", "failed"])
                )
                .values(status="cancelled")
            )

            cancelled_count = result.rowcount
            await session.commit()

            if cancelled_count > 0:
                logger.info(f"Отменено {cancelled_count} уведомлений для пользователя {user_id}")
            return cancelled_count

    except Exception as e:
        logger.error(f"Ошибка отмены уведомлений для пользователя {user_id}: {e}")
        return 0


def register_user_events_handlers(dp):
    """Регистрация обработчиков событий пользователей"""
    dp.include_router(router)
