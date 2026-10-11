# logger.py
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger


MAX_LOG_FILE_BYTES = 10 * 1024 * 1024


def secure_opener(path: str, flags: int) -> int:
    return os.open(path, flags, 0o600)


def rotate_log(message, file) -> bool:
    """Start a new file on a local calendar day or at the size limit."""
    day = message.record["time"].strftime("%Y-%m-%d")
    return (
        day not in Path(file.name).name
        or file.tell() + len(message.encode("utf-8")) > MAX_LOG_FILE_BYTES
    )


load_dotenv(Path(__file__).parent.parent / "config" / ".env")


def setup_logging(
    log_level: str = "INFO",
    log_dir: Path = Path("logs"),
    console_output: bool = True,
) -> None:
    log_dir.mkdir(mode=0o700, exist_ok=True)
    current_utc_time = datetime.now(UTC)
    retention = f"{int(os.getenv('LOG_RETENTION_DAYS', '30'))} days"

    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <5}</level> | "
        "<cyan>{module}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    logger.remove()

    if console_output:
        logger.add(
            sys.stdout,
            level=log_level,
            format=log_format,
            colorize=True,
            backtrace=False,
            diagnose=False,
            filter=lambda record: (
                record["level"].name
                in ["INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"]
            ),
        )

    try:
        logger.add(
            log_dir / "app_{time:YYYY-MM-DD}.log",
            level=log_level,
            format=log_format,
            rotation=rotate_log,
            retention=retention,
            compression="zip",
            encoding="utf-8",
            opener=secure_opener,
            enqueue=True,
            catch=True,
            backtrace=False,
            diagnose=False,
        )

        logger.add(
            log_dir / "app_jsonl_{time:YYYY-MM-DD}.log",
            level=log_level,
            serialize=True,
            rotation=rotate_log,
            retention=retention,
            compression="zip",
            encoding="utf-8",
            opener=secure_opener,
            enqueue=True,
            catch=True,
            backtrace=False,
            diagnose=False,
        )

        logger.add(
            log_dir / "errors_{time:YYYY-MM-DD}.log",
            level="ERROR",
            format=log_format,
            rotation=rotate_log,
            retention=retention,
            compression="zip",
            encoding="utf-8",
            opener=secure_opener,
            enqueue=True,
            catch=True,
            backtrace=False,
            diagnose=False,
        )
    except Exception as e:
        print(f"Ошибка настройки логирования: {e}")
        raise

    logger.info("Логгер успешно настроен")
    logger.info(f"Директория логов: {log_dir.absolute()}")
    logger.info(f"UTC время: {current_utc_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    logger.info(f"Ротация: 10 MiB на файл, хранение архивов {retention}")
    logger.info(f"Дата запуска: {current_utc_time.date()}")


def get_logger() -> logger:
    return logger


setup_logging(
    log_level=os.getenv("LOG_LEVEL", "INFO"),
    log_dir=Path(os.getenv("LOG_DIR", "logs")),
    console_output=os.getenv("CONSOLE_LOGS", "true").lower() == "true",
)
