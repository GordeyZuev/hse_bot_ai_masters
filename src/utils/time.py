import re
from datetime import UTC, datetime, time, timedelta

import pytz
from timezonefinder import TimezoneFinder


def utc_now() -> datetime:
    """Return current UTC time as timezone-aware datetime."""
    return datetime.now(UTC)


def ensure_aware_utc(dt: datetime) -> datetime:
    """Convert any datetime to aware UTC. If naive, assume it is UTC and attach tzinfo."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def get_timezone(tz_name: str) -> pytz.BaseTzInfo:
    """Return timezone by name, supporting strings like 'UTC+05:00' or 'UTC-3'."""
    if not tz_name:
        return pytz.UTC
    # Support 'UTC+HH:MM' or 'UTC+H' patterns
    m = re.fullmatch(
        r"UTC([+-])(\d{1,2})(?::?(\d{2}))?", tz_name.strip(), flags=re.IGNORECASE
    )
    if m:
        sign, hours_str, minutes_str = m.groups()
        hours = int(hours_str)
        minutes = int(minutes_str) if minutes_str else 0
        total_minutes = hours * 60 + minutes
        if sign == "-":
            total_minutes = -total_minutes
        return pytz.FixedOffset(total_minutes)
    try:
        return pytz.timezone(tz_name)
    except Exception:
        return pytz.UTC


def to_user_timezone(dt: datetime, tz_name: str) -> datetime:
    """Convert UTC datetime to user's timezone."""
    if dt is None:
        return None
    user_tz = get_timezone(tz_name)
    return ensure_aware_utc(dt).astimezone(user_tz)


def localize_naive_and_convert_to_utc(
    dt: datetime, default_tz_name: str = "Europe/Moscow"
) -> datetime:
    """If datetime is naive, localize with provided tz, then convert to UTC; if aware, convert to UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        tz = get_timezone(default_tz_name)
        dt = tz.localize(dt)
    return dt.astimezone(UTC)


def make_user_window_utc(
    days: int, user_tz_name: str
) -> tuple[datetime, datetime, datetime, datetime]:
    """Compute (now_local, end_local, now_utc, end_utc) for the user window of given days."""
    user_tz = get_timezone(user_tz_name)
    now_local = datetime.now(user_tz)
    end_local = now_local + timedelta(days=days)
    now_utc = now_local.astimezone(UTC)
    end_utc = end_local.astimezone(UTC)
    return now_local, end_local, now_utc, end_utc


def format_offset_from_moscow_label(tz_name: str) -> str:
    """Return human label like 'МСК', 'МСК +2' or 'МСК -1' for given timezone name.
    Uses current offsets (accounts for DST).
    """
    try:
        user_tz = get_timezone(tz_name)
        msk_tz = pytz.timezone("Europe/Moscow")
        now_utc = datetime.now(UTC)
        user_off = now_utc.astimezone(user_tz).utcoffset() or timedelta(0)
        msk_off = now_utc.astimezone(msk_tz).utcoffset() or timedelta(0)
        diff_hours = int(round((user_off - msk_off).total_seconds() / 3600))
        if diff_hours == 0:
            return "МСК"
        sign = "+" if diff_hours > 0 else "-"
        return f"МСК {sign}{abs(diff_hours)}"
    except Exception:
        return "МСК"


# -------- Location-based timezone detection --------


def get_timezone_from_location(latitude: float, longitude: float) -> str:
    """Get timezone name from latitude and longitude coordinates.
    Returns IANA timezone name or 'Europe/Moscow' as fallback.
    """
    try:
        tf = TimezoneFinder()
        timezone_name = tf.timezone_at(lat=latitude, lng=longitude)

        if timezone_name:
            # Validate that the timezone exists in pytz
            try:
                pytz.timezone(timezone_name)
                return timezone_name
            except pytz.UnknownTimeZoneError:
                pass

        # Fallback to Europe/Moscow if no timezone found or invalid
        return "Europe/Moscow"

    except Exception:
        # Fallback to Europe/Moscow on any error
        return "Europe/Moscow"


def get_timezone_from_location_with_city(
    latitude: float, longitude: float
) -> tuple[str, str]:
    """Get timezone name and city name from coordinates.
    Returns (timezone_name, city_name) tuple.
    """
    timezone_name = get_timezone_from_location(latitude, longitude)

    # Try to get a more human-readable city name
    try:
        city_name = "Ваше местоположение"

        if timezone_name:
            # Extract city from timezone name (e.g., "Europe/Moscow" -> "Moscow")
            parts = timezone_name.split("/")
            if len(parts) > 1:
                city_name = parts[-1].replace("_", " ")

        return timezone_name, city_name

    except Exception:
        return timezone_name, "Ваше местоположение"


# -------- Sleep time checking --------


def is_sleep_time(sleep_start: time | None, sleep_end: time | None, user_tz_name: str = "Europe/Moscow") -> bool:
    """Проверить, попадает ли текущее время пользователя в диапазон сна.

    Args:
        sleep_start: Время начала сна (HH:MM:SS) или None
        sleep_end: Время конца сна (HH:MM:SS) или None
        user_tz_name: Часовой пояс пользователя

    Returns:
        True если текущее время попадает в диапазон сна, False иначе
        Если sleep_start или sleep_end == None, возвращает False (сон не настроен)
    """
    if sleep_start is None or sleep_end is None:
        return False

    # Получаем текущее время в часовом поясе пользователя
    user_tz = get_timezone(user_tz_name)
    now_local = datetime.now(user_tz)
    current_time = now_local.time()

    # Если начало > конца, значит сон пересекает полночь (например, 23:00 - 08:00)
    if sleep_start > sleep_end:
        # Сон с конца дня до начала следующего дня
        # Текущее время должно быть >= sleep_start ИЛИ <= sleep_end
        return current_time >= sleep_start or current_time <= sleep_end
    else:
        # Обычный случай: сон в пределах одного дня (например, 01:00 - 09:00)
        # НО если начало == конец, это ошибка (не должно быть так)
        if sleep_start == sleep_end:
            return False
        return sleep_start <= current_time <= sleep_end
