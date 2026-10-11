import os
import stat
from datetime import datetime
from types import SimpleNamespace

from src.utils.logger import MAX_LOG_FILE_BYTES, rotate_log, secure_opener


class LogMessage(str):
    def __new__(cls, value, when):
        instance = super().__new__(cls, value)
        instance.record = {"time": when}
        return instance


def test_log_rotates_on_date_or_size() -> None:
    message = LogMessage("entry", datetime(2026, 10, 11))
    current = SimpleNamespace(name="app_2026-10-11.log", tell=lambda: 10)
    previous = SimpleNamespace(name="app_2026-10-10.log", tell=lambda: 10)
    full = SimpleNamespace(name="app_2026-10-11.log", tell=lambda: MAX_LOG_FILE_BYTES)

    assert not rotate_log(message, current)
    assert rotate_log(message, previous)
    assert rotate_log(message, full)


def test_new_log_is_private(tmp_path) -> None:
    path = tmp_path / "app.log"
    handle = secure_opener(str(path), os.O_CREAT | os.O_WRONLY)
    os.close(handle)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
