from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from src.core.database import db_manager
from src.core.models import ChatGroup, User
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
            chat = event.chat if hasattr(event, "chat") else (event.message.chat if hasattr(event, "message") else None)
            if chat and chat.type in ["group", "supergroup"]:
                await self.update_chat_title(chat)
        except Exception as e:
            logger.debug(f"Не удалось обновить chat_title в middleware: {e}")

        return await handler(event, data)

    async def get_or_create_user(self, tg_user) -> User:
        """Получить или создать пользователя в БД"""
        async with db_manager.async_session() as session:
            try:
                # Ищем существующего пользователя

                stmt = select(User).where(User.tg_user_id == tg_user.id)
                result = await session.execute(stmt)
                user = result.scalar_one_or_none()
                current_time = utc_now()

                if user:
                    # Обновляем информацию о пользователе
                    user.first_name = tg_user.first_name
                    user.last_name = tg_user.last_name
                    user.username = tg_user.username
                    user.last_activity = current_time
                else:
                    # Создаем нового пользователя
                    user = User(
                        tg_user_id=tg_user.id,
                        first_name=tg_user.first_name,
                        last_name=tg_user.last_name,
                        username=tg_user.username,
                        created_at=current_time,
                        last_activity=current_time,
                        timezone="Europe/Moscow",
                    )
                    session.add(user)
                    logger.info(
                        f"(U) {tg_user.id} - Новый пользователь @{tg_user.username}"
                    )

                    # Создаем настройки уведомлений по умолчанию для нового пользователя
                    settings = await db_manager.create_user_notification_settings(
                        tg_user.id
                    )
                    session.add(settings)

                await session.commit()
                await session.refresh(user)
                return user

            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка работы с пользователем {tg_user.id}: {e}")
                raise

    async def update_chat_title(self, chat):
        """Обновить название чата в БД, если оно изменилось"""
        try:
            async with db_manager.async_session() as session:
                stmt = select(ChatGroup).where(ChatGroup.chat_id == chat.id)
                result = await session.execute(stmt)
                chat_group = result.scalar_one_or_none()

                if chat_group and chat.title and chat_group.chat_title != chat.title:
                    # Обновляем только если название изменилось
                    chat_group.chat_title = chat.title
                    await session.commit()
                    logger.debug(f"Обновлено название чата {chat.id}: {chat.title}")
        except Exception as e:
            # Игнорируем ошибки обновления chat_title (не критично)
            logger.debug(f"Не удалось обновить chat_title для чата {chat.id if chat else 'unknown'}: {e}")
