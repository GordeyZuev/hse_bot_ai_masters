from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message
from sqlalchemy import case, select
from sqlalchemy.dialects.postgresql import insert

from src.core.database import db_manager
from src.core.models import User, UserNotificationSettings
from src.utils import get_logger
from src.utils.time import utc_now


logger = get_logger()


class DatabaseMiddleware(BaseMiddleware):
    """Middleware для автоматического создания пользователей и работы с БД"""

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        user = event.from_user
        if not user:
            return await handler(event, data)

        try:
            if not db_manager.initialized:
                await db_manager.ensure_initialized()

            db_user = await self.get_or_create_user(user)
            data["db_user"] = db_user

        except Exception as e:
            logger.error(f"Ошибка в DatabaseMiddleware: {e}")
            raise

        # Обновляем chat_title для групповых чатов (не блокируем основной flow при ошибках)
        try:
            chat = (
                event.chat
                if hasattr(event, "chat")
                else (event.message.chat if hasattr(event, "message") else None)
            )
            if chat and chat.type in ["group", "supergroup"]:
                await self.update_chat_title(chat)
        except Exception as e:
            logger.debug(f"Не удалось обновить chat_title в middleware: {e}")

        return await handler(event, data)

    async def get_or_create_user(self, tg_user) -> User:
        """Получить или создать пользователя в БД"""
        async with db_manager.async_session() as session:
            try:
                current_time = utc_now()
                activity_threshold = current_time - timedelta(minutes=15)
                user_stmt = (
                    insert(User)
                    .values(
                        tg_user_id=tg_user.id,
                        first_name=tg_user.first_name,
                        last_name=tg_user.last_name,
                        username=tg_user.username,
                        created_at=current_time,
                        last_activity=current_time,
                        timezone="Europe/Moscow",
                        is_active=True,
                    )
                    .on_conflict_do_update(
                        index_elements=[User.tg_user_id],
                        set_={
                            "first_name": tg_user.first_name,
                            "last_name": tg_user.last_name,
                            "username": tg_user.username,
                            "last_activity": case(
                                (
                                    User.last_activity.is_(None)
                                    | (User.last_activity < activity_threshold),
                                    current_time,
                                ),
                                else_=User.last_activity,
                            ),
                        },
                    )
                    .returning(User)
                )
                user = (await session.execute(user_stmt)).scalar_one()
                settings_stmt = (
                    insert(UserNotificationSettings)
                    .values(user_id=tg_user.id)
                    .on_conflict_do_nothing(constraint="unique_user_settings")
                    .returning(UserNotificationSettings.id)
                )
                created_settings_id = (
                    await session.execute(settings_stmt)
                ).scalar_one_or_none()
                await session.commit()
                if created_settings_id is not None:
                    logger.info(
                        f"(U) {tg_user.id} - Новый пользователь @{tg_user.username}"
                    )
                    try:
                        from src.bot.services.notification_scheduler_service import (
                            notification_scheduler_service,
                        )

                        await notification_scheduler_service.schedule_notifications_for_user_settings_creation(
                            tg_user.id
                        )
                    except Exception as scheduling_error:
                        logger.warning(
                            f"Не удалось запланировать уведомления новому пользователю {tg_user.id}: {scheduling_error}"
                        )
                return user

            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка работы с пользователем {tg_user.id}: {e}")
                raise

    async def update_chat_title(self, chat):
        """Обновить название чата в БД, если оно изменилось"""
        try:
            async with db_manager.async_session() as session:
                from src.core.models import ChatGroup

                stmt = select(ChatGroup).where(ChatGroup.chat_id == chat.id)
                result = await session.execute(stmt)
                chat_obj = result.scalar_one_or_none()

                if chat_obj and chat.title and chat_obj.chat_title != chat.title:
                    # Обновляем только если название изменилось
                    chat_obj.chat_title = chat.title
                    await session.commit()
                    logger.debug(f"Обновлено название чата {chat.id}: {chat.title}")
        except Exception as e:
            # Игнорируем ошибки обновления chat_title (не критично)
            logger.debug(
                f"Не удалось обновить chat_title для чата {chat.id if chat else 'unknown'}: {e}"
            )
