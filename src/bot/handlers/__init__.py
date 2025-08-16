"""
Хендлеры для телеграм бота HSE.
"""
from aiogram import Dispatcher

from .start import register_start_handlers
from .help import register_help_handlers
from .subscriptions import register_subscription_handlers
from .settings import register_settings_handlers
from .common import register_common_handlers


def register_handlers(dp: Dispatcher) -> None:
    """
    Регистрирует все хендлеры бота.
    
    Args:
        dp: Диспетчер aiogram
    """
    # Порядок регистрации важен - более специфичные хендлеры должны быть первыми
    register_start_handlers(dp)
    register_help_handlers(dp)
    register_subscription_handlers(dp)
    register_settings_handlers(dp)
    register_common_handlers(dp)  # Общие хендлеры регистрируем последними