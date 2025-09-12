from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from datetime import datetime
import pytz

from src.core.database import db_manager
from src.core.models import User, UserNotificationSettings
from src.utils import get_logger
from sqlalchemy import select
from src.utils.time import utc_now

logger = get_logger()

class DatabaseMiddleware(BaseMiddleware):
    """Middleware для автоматического создания пользователей и работы с БД"""
    
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        user = event.from_user
        if not user:
            return await handler(event, data)
        
        try:
            await db_manager.ensure_initialized()
            
            db_user = await self.get_or_create_user(user)
            data['db_user'] = db_user
            
        except Exception as e:
            logger.error(f"Ошибка в DatabaseMiddleware: {e}")
            raise
        
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
                    user.last_activity_ts = current_time
                else:
                    # Создаем нового пользователя
                    user = User(
                        tg_user_id=tg_user.id,
                        first_name=tg_user.first_name,
                        last_name=tg_user.last_name,
                        username=tg_user.username,
                        subscribed_at=current_time,
                        last_activity_ts=current_time,
                        timezone='Europe/Moscow'
                    )
                    session.add(user)
                    logger.info(f"Создан новый пользователь: {tg_user.id} (@{tg_user.username})")
                    
                    # Создаем настройки уведомлений по умолчанию для нового пользователя
                    settings = await db_manager.create_user_notification_settings(tg_user.id)
                    session.add(settings)
                
                await session.commit()
                await session.refresh(user)
                return user
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка работы с пользователем {tg_user.id}: {e}")
                raise