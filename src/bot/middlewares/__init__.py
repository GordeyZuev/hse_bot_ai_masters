from aiogram import Dispatcher

from .database import DatabaseMiddleware
from .group_chat import GroupChatMiddleware
from .private_chat import PrivateChatMiddleware


def register_middlewares(dp: Dispatcher):
    """Регистрация всех middleware"""
    # Сначала регистрируем DatabaseMiddleware для работы с БД
    dp.message.middleware(DatabaseMiddleware())
    dp.callback_query.middleware(DatabaseMiddleware())

    # Затем GroupChatMiddleware для обработки ошибок групповых чатов
    dp.message.middleware(GroupChatMiddleware())
    dp.callback_query.middleware(GroupChatMiddleware())

    # И PrivateChatMiddleware для обработки ошибок личных чатов
    dp.message.middleware(PrivateChatMiddleware())
    dp.callback_query.middleware(PrivateChatMiddleware())
