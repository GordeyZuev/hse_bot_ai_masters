"""Утилиты для форматирования уведомлений (DRY/KISS)."""

from datetime import UTC, datetime

import pytz


def format_time_remaining(deadline_ts: datetime, now: datetime | None = None) -> str:
    """Форматировать остаток времени до дедлайна.

    Args:
        deadline_ts: Время дедлайна (UTC, aware)
        now: Текущее время (UTC, aware), если None - используется datetime.now(UTC)

    Returns:
        Строка вида "(X дн.)", "(X ч.)", "(X мин.)" или "(сегодня!)"
    """
    if now is None:
        now = datetime.now(UTC)

    delta = deadline_ts - now

    if delta.days > 0:
        return f"({delta.days} дн.)"
    elif delta.seconds >= 3600:
        hours = delta.seconds // 3600
        return f"({hours} ч.)"
    elif delta.seconds >= 60:
        minutes = delta.seconds // 60
        return f"({minutes} мин.)"
    else:
        return "(сегодня!)"


def format_deadline_datetime(deadline_ts: datetime, tz_name: str = "Europe/Moscow") -> str:
    """Форматировать дату/время дедлайна в указанном часовом поясе.

    Args:
        deadline_ts: Время дедлайна (UTC, aware)
        tz_name: Название часового пояса (по умолчанию "Europe/Moscow")

    Returns:
        Строка вида "DD.MM.YYYY HH:MM" или "DD.MM.YYYY в HH:MM"
    """
    user_tz = pytz.timezone(tz_name)
    local_time = deadline_ts.astimezone(user_tz)
    return local_time.strftime("%d.%m.%Y %H:%M")


def format_deadline_datetime_with_time_word(
    deadline_ts: datetime, tz_name: str = "Europe/Moscow"
) -> str:
    """Форматировать дату/время дедлайна с словом "в" перед временем.

    Args:
        deadline_ts: Время дедлайна (UTC, aware)
        tz_name: Название часового пояса (по умолчанию "Europe/Moscow")

    Returns:
        Строка вида "DD.MM.YYYY в HH:MM"
    """
    user_tz = pytz.timezone(tz_name)
    local_time = deadline_ts.astimezone(user_tz)
    return local_time.strftime("%d.%m.%Y в %H:%M")

