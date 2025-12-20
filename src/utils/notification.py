"""
Утилиты для работы с уведомлениями.
"""

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from src.core.models import User, UserNotificationSettings


def apply_sleep_mode(
    user: "User",
    settings: "UserNotificationSettings | None",
    message_text: str
) -> tuple[str, bool]:
    """
    Применить режим сна к тексту сообщения и определить флаг disable_notification.

    Args:
        user: Объект пользователя с полем timezone
        settings: Настройки уведомлений с полями sleep_start_time и sleep_end_time
        message_text: Исходный текст сообщения

    Returns:
        tuple[str, bool]:
            - Модифицированный текст сообщения (с припиской о сне, если нужно)
            - Флаг disable_notification (True если сейчас время сна)
    """
    from src.utils.time import is_sleep_time

    is_sleep = False

    if settings and user:
        user_tz_name = user.timezone if user.timezone else "Europe/Moscow"
        is_sleep = is_sleep_time(
            settings.sleep_start_time,
            settings.sleep_end_time,
            user_tz_name
        )

        if is_sleep:
            message_text = message_text + "\n\n<i>Отправлено без уведомления. Доброй ночи! 😴</i>"

    return message_text, is_sleep
