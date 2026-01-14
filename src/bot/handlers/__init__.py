from aiogram import Dispatcher

from .admin import register_admin_handlers
from .group_chat import register_group_chat_handlers
from .help import register_help_handlers
from .settings import register_settings_handlers
from .start import register_start_handlers
from .subscriptions import register_subscription_handlers
from .tasks import register_task_handlers
from .workshop import register_workshop_handlers


def register_handlers(dp: Dispatcher):
    """Регистрация всех handlers"""
    register_start_handlers(dp)
    register_help_handlers(dp)
    register_subscription_handlers(dp)
    register_task_handlers(dp)  # Бывший register_deadline_handlers
    register_settings_handlers(dp)
    register_group_chat_handlers(dp)
    register_admin_handlers(dp)
    register_workshop_handlers(dp)
