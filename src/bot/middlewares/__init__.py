from aiogram import Dispatcher

from .database import DatabaseMiddleware

def register_middlewares(dp: Dispatcher):
    """Регистрация всех middleware"""
    dp.message.middleware(DatabaseMiddleware())
    dp.callback_query.middleware(DatabaseMiddleware())