"""
Middleware для телеграм бота HSE.
"""
from aiogram import Dispatcher

from .logging import LoggingMiddleware
from .database import DatabaseMiddleware


def register_middlewares(dp: Dispatcher) -> None:
    """
    Регистрирует все middleware для бота.
    
    Args:
        dp: Диспетчер aiogram
    """
    # Регистрируем middleware в правильном порядке
    dp.message.middleware(LoggingMiddleware())
    dp.callback_query.middleware(LoggingMiddleware())
    
    dp.message.middleware(DatabaseMiddleware())
    dp.callback_query.middleware(DatabaseMiddleware())