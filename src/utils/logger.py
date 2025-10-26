# logger.py
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

load_dotenv(Path(__file__).parent.parent / "config" / ".env")


def setup_logging(
    log_level: str = "INFO",
    log_dir: Path = Path("logs"),
    console_output: bool = True,
) -> None:
    log_dir.mkdir(exist_ok=True)
    current_utc_time = datetime.now(UTC)

    log_format = (
        "<green>{time:YY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <5}</level> | "
        "<cyan>{module}</cyan>:<cyan>{function}</cyan>:{line} | "
        "<level>{message}</level>"
    )

    json_format = (
        '{{"timestamp": "{time:YYYY-MM-DD HH:mm:ss.SSS}", '
        '"level": "{level}", '
        '"module": "{module}", '
        '"function": "{function}", '
        '"line": {line}, '
        '"process": {process}, '
        '"thread": {thread}, '
        '"message": "{message}"}}'
    )

    logger.remove()

    if console_output:
        logger.add(
            sys.stdout,
            level=log_level,
            format=log_format,
            colorize=True,
            backtrace=True,
            diagnose=True,
            filter=lambda record: record["level"].name in ["INFO", "WARNING", "ERROR", "CRITICAL"],
        )

    try:
        logger.add(
            log_dir / "app_{time:YYYY-MM-DD}.log",
            level=log_level,
            format=log_format,
            rotation="1 week",
            retention="1 month",
            compression="zip",
            encoding="utf-8",
            enqueue=True,
            catch=True,
        )

        logger.add(
            log_dir / "app_json_{time:YYYY-MM-DD}.log",
            level=log_level,
            format=json_format,
            rotation="1 week",
            retention="1 month",
            compression="zip",
            encoding="utf-8",
            enqueue=True,
            catch=True,
        )

        logger.add(
            log_dir / "errors_{time:YYYY-MM}.log",
            level="ERROR",
            format=log_format,
            rotation="1 month",
            retention="1 month",
            compression="zip",
            encoding="utf-8",
            enqueue=True,
            catch=True,
        )
    except Exception as e:
        print(f"Ошибка настройки логирования: {e}")
        raise

    logger.info("Логгер успешно настроен")
    logger.info(f"Директория логов: {log_dir.absolute()}")
    logger.info(f"UTC время: {current_utc_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    logger.info("Ротация: обычные логи - 1 неделя, ошибки - 1 месяц")
    logger.info(f"Текущий файл лога: app_{current_utc_time.strftime('%Y-%m-%d')}.log")


def get_logger() -> logger:
    return logger


setup_logging(
    log_level=os.getenv("LOG_LEVEL", "INFO"),
    log_dir=Path(os.getenv("LOG_DIR", "logs")),
    console_output=os.getenv("CONSOLE_LOGS", "false").lower() == "true",
)
