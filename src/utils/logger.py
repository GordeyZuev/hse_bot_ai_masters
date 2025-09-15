# logger.py
import sys
from pathlib import Path
from loguru import logger
import os
from datetime import datetime, timezone
import pytz

def setup_logging(
    log_level: str = "INFO",
    rotation: str = "00:00",  # Ротация в полночь по московскому времени
    retention: str = "30 days",
    log_dir: Path = Path("logs")
) -> None:
    """
    Настройка логгера для продакшн-окружения
    """
    
    # Создаем директорию для логов если не существует
    log_dir.mkdir(exist_ok=True)
    
    # Текущее время в UTC
    current_utc_time = datetime.now(timezone.utc)
    
    # Формат для логов
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )
    
    # Правильный JSON формат (убраны лишние кавычки)
    json_format = (
        '{{"timestamp": "{time:YYYY-MM-DD HH:mm:ss.SSS}", '
        '"level": "{level}", '
        '"name": "{name}", '
        '"function": "{function}", '
        '"line": {line}, '
        '"message": "{message}"}}'
    )
    
    # Удаляем стандартный обработчик
    logger.remove()
    
    # Консольный вывод
    logger.add(
        sys.stdout,
        level=log_level,
        format=log_format,
        colorize=True,
        backtrace=True,
        diagnose=True
    )
    
    # Файловый вывод (ротация по времени в полночь)
    logger.add(
        log_dir / "app_{time:YYYY-MM-DD}.log",
        level=log_level,
        format=log_format,
        rotation=rotation,
        retention=retention,
        compression="zip",
        encoding="utf-8",
        enqueue=True  # Асинхронная запись для лучшей производительности
    )
    
    # JSON лог для машинной обработки
    logger.add(
        log_dir / "app_json_{time:YYYY-MM-DD}.log",
        level=log_level,
        format=json_format,
        rotation=rotation,
        retention=retention,
        compression="zip",
        encoding="utf-8",
        enqueue=True,
        catch=True  # Перехватывать ошибки записи
    )
    
    # Отдельный файл для ошибок
    logger.add(
        log_dir / "errors_{time:YYYY-MM-DD}.log",
        level="ERROR",
        format=log_format,
        rotation=rotation,
        retention="90 days",
        compression="zip",
        encoding="utf-8",
        enqueue=True
    )
    
    # Логирование старта с диагностикой
    logger.info("Логгер успешно настроен")
    logger.info(f"Директория логов: {log_dir.absolute()}")
    logger.info(f"UTC время: {current_utc_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    logger.info(f"Ротация настроена на: {rotation}")
    logger.info(f"Текущий файл лога: app_{current_utc_time.strftime('%Y-%m-%d')}.log")

def get_logger() -> logger:
    """Получить настроенный логгер"""
    return logger

# Инициализация при импорте
setup_logging(
    log_level=os.getenv("LOG_LEVEL", "INFO"),
    log_dir=Path(os.getenv("LOG_DIR", "logs"))
)