from datetime import datetime, timezone, timedelta
import pytz
import re


def utc_now() -> datetime:
    """Return current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


def ensure_aware_utc(dt: datetime) -> datetime:
    """Convert any datetime to aware UTC. If naive, assume it is UTC and attach tzinfo."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_timezone(tz_name: str) -> pytz.BaseTzInfo:
    """Return timezone by name, supporting strings like 'UTC+05:00' or 'UTC-3'."""
    if not tz_name:
        return pytz.UTC
    # Support 'UTC+HH:MM' or 'UTC+H' patterns
    m = re.fullmatch(r"UTC([+-])(\d{1,2})(?::?(\d{2}))?", tz_name.strip(), flags=re.IGNORECASE)
    if m:
        sign, hours_str, minutes_str = m.groups()
        hours = int(hours_str)
        minutes = int(minutes_str) if minutes_str else 0
        total_minutes = hours * 60 + minutes
        if sign == '-':
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


def localize_naive_and_convert_to_utc(dt: datetime, default_tz_name: str = 'Europe/Moscow') -> datetime:
    """If datetime is naive, localize with provided tz, then convert to UTC; if aware, convert to UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        tz = get_timezone(default_tz_name)
        dt = tz.localize(dt)
    return dt.astimezone(timezone.utc)


def make_user_window_utc(days: int, user_tz_name: str) -> tuple[datetime, datetime, datetime, datetime]:
    """Compute (now_local, end_local, now_utc, end_utc) for the user window of given days."""
    user_tz = get_timezone(user_tz_name)
    now_local = datetime.now(user_tz)
    end_local = now_local + timedelta(days=days)
    now_utc = now_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)
    return now_local, end_local, now_utc, end_utc


# -------- Timezone selection helpers --------

def format_fixed_utc_label(utc_total: float) -> str:
    """Format a fixed UTC label like 'UTC+03' for given utc_total hours (float)."""
    sign = '+' if utc_total >= 0 else '-'
    abs_total = abs(int(utc_total))
    return f"UTC{sign}{abs_total:02d}"


def propose_timezones_for_utc_offset(utc_total: float, max_results: int = 12) -> tuple[list[str], str]:
    """Return (candidate_iana_timezones, fixed_label) for given utc_total hours.
    Candidates are sorted by common region preference and name.
    """
    now_utc = datetime.now(timezone.utc)
    total_minutes = int(utc_total * 60)
    candidates: list[str] = []
    for tz_name in pytz.all_timezones:
        try:
            tzinfo = pytz.timezone(tz_name)
            offset = now_utc.astimezone(tzinfo).utcoffset()
            if offset is None:
                continue
            if int(offset.total_seconds() // 60) == total_minutes:
                candidates.append(tz_name)
        except Exception:
            continue
    priority_order = ['Europe/', 'Asia/', 'America/', 'Africa/', 'Australia/']
    def prio(name: str) -> int:
        for i, pref in enumerate(priority_order):
            if name.startswith(pref):
                return i
        return len(priority_order)
    candidates.sort(key=lambda n: (prio(n), n))
    fixed_label = format_fixed_utc_label(utc_total)
    return candidates[:max_results], fixed_label


def parse_utc_offset(user_input: str) -> float:
    """Parse input like '+N' or '-N' as hours relative to UTC and return utc_total hours as float.
    Raises ValueError on invalid input or out-of-range.
    """
    text = (user_input or '').strip()
    match = re.fullmatch(r"([+-]?)(\d{1,2})", text)
    if not match:
        raise ValueError("format")
    sign, hours_str = match.groups()
    hours = int(hours_str)
    if hours > 14:
        raise ValueError("range")
    total = float(hours)
    if sign == '-':
        total = -total
    if total < -12 or total > 14:
        raise ValueError("utc_bounds")
    return total


def format_offset_from_moscow_label(tz_name: str) -> str:
    """Return human label like 'МСК', 'МСК +2' or 'МСК -1' for given timezone name.
    Uses current offsets (accounts for DST).
    """
    try:
        user_tz = get_timezone(tz_name)
        msk_tz = pytz.timezone('Europe/Moscow')
        now_utc = datetime.now(timezone.utc)
        user_off = now_utc.astimezone(user_tz).utcoffset() or timedelta(0)
        msk_off = now_utc.astimezone(msk_tz).utcoffset() or timedelta(0)
        diff_hours = int(round((user_off - msk_off).total_seconds() / 3600))
        if diff_hours == 0:
            return "МСК"
        sign = '+' if diff_hours > 0 else '-'
        return f"МСК {sign}{abs(diff_hours)}"
    except Exception:
        return "МСК"


