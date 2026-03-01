"""Утилиты для форматирования уведомлений."""

from datetime import UTC, datetime

import pytz

DATE_FMT_SHORT = "%d.%m.%y %H:%M"
DATE_FMT_WITH_WORD = "%d.%m.%y в %H:%M"


def format_time_remaining(deadline_ts: datetime, now: datetime | None = None) -> str:
    """Форматировать остаток времени до дедлайна.

    Правило:
    - Если осталось > 24 ч: показываем дни (округляем вверх по суткам).
    - Если осталось <= 24 ч и > 0: показываем часы (округляем вверх).
    """
    if now is None:
        now = datetime.now(UTC)

    total_seconds = (deadline_ts - now).total_seconds()

    if total_seconds <= 0:
        return ""

    hours = int((total_seconds + 3599) // 3600)  # ceil без float

    if hours > 24:
        days = (hours + 23) // 24  # ceil по суткам
        return f"({days} дн.)"

    return f"({hours} ч.)"


def format_deadline_datetime_with_time_word(
    deadline_ts: datetime, tz_name: str = "Europe/Moscow"
) -> str:
    """Форматировать дату/время дедлайна с словом "в" перед временем.

    Args:
        deadline_ts: Время дедлайна (UTC, aware)
        tz_name: Название часового пояса (по умолчанию "Europe/Moscow")

    Returns:
        Строка вида "DD.MM.YY в HH:MM"
    """
    user_tz = pytz.timezone(tz_name)
    local_time = deadline_ts.astimezone(user_tz)
    return local_time.strftime(DATE_FMT_WITH_WORD)


def format_deadline_tg_time(
    deadline_ts: datetime,
    format_str: str = "dt",
    fallback: str | None = None,
    tz_name: str | None = None,
) -> str:
    """HTML-тег tg-time для отображения даты в локальном формате пользователя.

    Telegram отобразит дату в языке и часовом поясе пользователя.
    Fallback (для старых клиентов) — в tz_name пользователя.

    Args:
        deadline_ts: Время дедлайна (UTC, aware)
        format_str: Формат (d=кор.дата, D=длин.дата, t=кор.время, T=полн.время, r=относит.)
        fallback: Текст для старых клиентов (если None — считается из tz_name)
        tz_name: Часовой пояс для fallback (Europe/Moscow по умолчанию)

    Returns:
        Строка HTML: <tg-time unix="..." format="...">fallback</tg-time>
    """
    unix_ts = int(deadline_ts.timestamp())
    if fallback is None:
        user_tz = pytz.timezone(tz_name or "Europe/Moscow")
        local_time = deadline_ts.astimezone(user_tz)
        fallback = local_time.strftime(DATE_FMT_SHORT)
    return f'<tg-time unix="{unix_ts}" format="{format_str}">{fallback}</tg-time>'


def format_duration(seconds: float) -> str:
    """Форматировать длительность в секундах в читаемый формат.

    Args:
        seconds: Количество секунд

    Returns:
        Строка вида "X мин. Y сек." или "X сек." для коротких длительностей
    """
    if seconds < 60:
        return f"{int(seconds)} сек."

    minutes = int(seconds // 60)
    secs = int(seconds % 60)

    if secs == 0:
        return f"{minutes} мин."
    return f"{minutes} мин. {secs} сек."

