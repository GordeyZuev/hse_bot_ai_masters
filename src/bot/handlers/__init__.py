from aiogram import Dispatcher

from .admin import register_admin_handlers
from .deadlines import register_deadline_handlers
from .help import register_help_handlers
from .settings import register_settings_handlers
from .start import register_start_handlers
from .subscriptions import register_subscription_handlers


def register_handlers(dp: Dispatcher):
    """Регистрация всех handlers"""
    register_start_handlers(dp)
    register_help_handlers(dp)
    register_subscription_handlers(dp)
    register_deadline_handlers(dp)
    register_settings_handlers(dp)
    register_admin_handlers(dp)
