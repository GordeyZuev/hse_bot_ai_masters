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


@router.chat_member()
async def handle_user_chat_member_update(update: ChatMemberUpdated):
    """Обработчик изменения статуса пользователя в чате с ботом"""
    try:
        # Проверяем, что это личный чат с ботом
        if update.chat.type != "private":
            return

        user_id = update.from_user.id
        old_status = update.old_chat_member.status
        new_status = update.new_chat_member.status

        logger.info(f"[USER] Статус пользователя {user_id} изменился: {old_status} → {new_status}")

        # Пользователь заблокировал бота
        if old_status in ["member"] and new_status in ["kicked", "left"]:
            await handle_user_blocked_bot(user_id)

        # Пользователь разблокировал бота
        elif old_status in ["kicked", "left"] and new_status in ["member"]:
            await handle_user_unblocked_bot(user_id)

    except Exception as e:
        logger.error(f"Ошибка обработки события изменения статуса пользователя: {e}")


async def handle_user_blocked_bot(user_id: int):
    """Обработка блокировки бота пользователем"""
    try:
        # Деактивируем пользователя
        success = await deactivate_user(user_id)

        if success:
            # Отменяем все запланированные уведомления пользователя
            cancelled_count = await cancel_user_notifications(user_id)

            logger.info(f"[USER] Пользователь {user_id} заблокировал бота. "
                       f"Отменено уведомлений: {cancelled_count}")
        else:
            logger.info(f"[USER] Пользователь {user_id} заблокировал бота (пользователь не найден в БД)")

    except Exception as e:
        logger.error(f"Ошибка обработки блокировки бота пользователем {user_id}: {e}")


async def handle_user_unblocked_bot(user_id: int):
    """Обработка разблокировки бота пользователем"""
    try:
        # Активируем пользователя
        success = await activate_user(user_id)

        if success:
            logger.info(f"[USER] Пользователь {user_id} разблокировал бота. Пользователь активирован.")
        else:
            logger.info(f"[USER] Пользователь {user_id} разблокировал бота (пользователь не найден в БД)")

    except Exception as e:
        logger.error(f"Ошибка обработки разблокировки бота пользователем {user_id}: {e}")


async def deactivate_user(user_id: int) -> bool:
    """Деактивация пользователя (при блокировке бота)"""
    try:
        async with db_manager.async_session() as session:
            from src.core.models.models import User

            user = await session.get(User, user_id)
            if user:
                user.is_active = False
                await session.commit()
                logger.info(f"Пользователь {user_id} деактивирован")
                return True
            return False
    except Exception as e:
        logger.error(f"Ошибка деактивации пользователя {user_id}: {e}")
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
                logger.info(f"Пользователь {user_id} активирован")
                return True
            return False
    except Exception as e:
        logger.error(f"Ошибка активации пользователя {user_id}: {e}")
        return False


async def cancel_user_notifications(user_id: int) -> int:
    """Отмена всех запланированных уведомлений пользователя (при блокировке бота)"""
    try:
        async with db_manager.async_session() as session:
            from sqlalchemy import update

            from src.core.models.models import ScheduledNotification

            # Обновляем статус всех запланированных уведомлений на 'cancelled'
            result = await session.execute(
                update(ScheduledNotification)
                .where(
                    ScheduledNotification.user_id == user_id,
                    ScheduledNotification.status == "scheduled"
                )
                .values(status="cancelled")
            )

            cancelled_count = result.rowcount
            await session.commit()

            logger.info(f"Отменено {cancelled_count} уведомлений для пользователя {user_id}")
            return cancelled_count

    except Exception as e:
        logger.error(f"Ошибка отмены уведомлений для пользователя {user_id}: {e}")
        return 0


def register_user_events_handlers(dp):
    """Регистрация обработчиков событий пользователей"""
    dp.include_router(router)
