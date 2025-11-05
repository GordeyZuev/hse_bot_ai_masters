from .logger import get_logger, get_week_monday, setup_logging
from .notification import apply_sleep_mode


# Ленивая загрузка функций из middleware для избежания циклических импортов
def _lazy_import_safe_edit_message():
    """Ленивый импорт safe_edit_message"""
    from src.bot.middlewares.private_chat import safe_edit_message
    return safe_edit_message


def _lazy_import_safe_send_message():
    """Ленивый импорт safe_send_message"""
    from src.bot.middlewares.private_chat import safe_send_message
    return safe_send_message


class _LazyFunction:
    """Прокси для ленивой загрузки функций, имитирует оригинальную функцию"""
    def __init__(self, loader):
        self._loader = loader
        self._func = None

    def __call__(self, *args, **kwargs):
        if self._func is None:
            self._func = self._loader()
        return self._func(*args, **kwargs)

    def __getattr__(self, name):
        if self._func is None:
            self._func = self._loader()
        return getattr(self._func, name)

    def __repr__(self):
        if self._func is None:
            return "<lazy function (not loaded yet)>"
        return repr(self._func)


safe_edit_message = _LazyFunction(_lazy_import_safe_edit_message)
safe_send_message = _LazyFunction(_lazy_import_safe_send_message)


__all__ = [
    "apply_sleep_mode",
    "get_logger",
    "get_week_monday",
    "safe_edit_message",
    "safe_send_message",
    "setup_logging",
]
