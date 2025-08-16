"""
Middleware для работы с базой данных.
"""
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

from src.db import UserCRUD, get_db_session
from src.utils import db_logger


class DatabaseMiddleware(BaseMiddleware):
    """Middleware для автоматического обновления активности пользователей."""
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        """
        Обрабатывает входящие обновления и обновляет активность пользователей.
        
        Args:
            handler: Следующий обработчик в цепочке
            event: Событие (Message, CallbackQuery, etc.)
            data: Данные контекста
        """
        user = None
        
        # Получаем информацию о пользователе
        if isinstance(event, (Message, CallbackQuery)):
            user = event.from_user
        
        # Обновляем активность пользователя
        if user:
            try:
                async with get_db_session() as session:
                    await UserCRUD.update_activity(session, user.id)
                    
                db_logger.debug(
                    f"Updated user activity",
                    user_id=user.id,
                    username=user.username
                )
                
            except Exception as e:
                db_logger.error(
                    f"Failed to update user activity: {str(e)}",
                    user_id=user.id,
                    username=user.username
                )
                # Не прерываем выполнение, если не удалось обновить активность
        
        # Добавляем сессию БД в контекст для использования в хендлерах
        try:
            async with get_db_session() as session:
                data["db_session"] = session
                result = await handler(event, data)
                return result
        except Exception as e:
            db_logger.error(f"Database error in middleware: {str(e)}")
            raise