"""
Middleware для логирования действий пользователей.
"""
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

from src.utils import bot_logger


class LoggingMiddleware(BaseMiddleware):
    """Middleware для логирования всех входящих обновлений."""
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        """
        Обрабатывает входящие обновления и логирует их.
        
        Args:
            handler: Следующий обработчик в цепочке
            event: Событие (Message, CallbackQuery, etc.)
            data: Данные контекста
        """
        user = None
        event_type = type(event).__name__
        
        # Получаем информацию о пользователе
        if isinstance(event, Message):
            user = event.from_user
            event_info = {
                "message_id": event.message_id,
                "text": event.text[:100] if event.text else None,
                "content_type": event.content_type,
                "chat_type": event.chat.type
            }
        elif isinstance(event, CallbackQuery):
            user = event.from_user
            event_info = {
                "callback_data": event.data,
                "message_id": event.message.message_id if event.message else None
            }
        else:
            event_info = {}
        
        # Логируем входящее событие
        if user:
            bot_logger.debug(
                f"Incoming {event_type}",
                user_id=user.id,
                username=user.username,
                **event_info
            )
        
        try:
            # Вызываем следующий обработчик
            result = await handler(event, data)
            
            # Логируем успешную обработку
            if user:
                bot_logger.debug(
                    f"Successfully processed {event_type}",
                    user_id=user.id,
                    username=user.username
                )
            
            return result
            
        except Exception as e:
            # Логируем ошибку
            if user:
                bot_logger.error(
                    f"Error processing {event_type}: {str(e)}",
                    user_id=user.id,
                    username=user.username,
                    error=str(e),
                    **event_info
                )
            else:
                bot_logger.error(f"Error processing {event_type}: {str(e)}")
            
            # Пробрасываем исключение дальше
            raise