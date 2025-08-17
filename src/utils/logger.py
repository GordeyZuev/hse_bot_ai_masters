# logger.py
import sys
from pathlib import Path
from loguru import logger
import os

def setup_logging(
    log_level: str = "INFO",
    rotation: str = "10 MB",
    retention: str = "30 days",
    log_dir: Path = Path("logs")
) -> None:
    """
    Настройка логгера для продакшн-окружения
    """
    
    # Создаем директорию для логов если не существует
    log_dir.mkdir(exist_ok=True)
    
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
    
    # Файловый вывод (ротация по размеру)
    logger.add(
        log_dir / "app_{time:YYYY-MM-DD}.log",
        level=log_level,
        format=log_format,
        rotation=rotation,
        retention=retention,
        compression="zip",
        encoding="utf-8"
    )
    
    # JSON лог для машинной обработки
    logger.add(
        log_dir / "app_json_{time:YYYY-MM-DD}.log",
        level=log_level,
        format=json_format,
        rotation=rotation,
        retention=retention,
        compression="zip",
        encoding="utf-8"
    )
    
    # Отдельный файл для ошибок
    logger.add(
        log_dir / "errors_{time:YYYY-MM-DD}.log",
        level="ERROR",
        format=log_format,
        rotation=rotation,
        retention="90 days",
        compression="zip",
        encoding="utf-8"
    )
    
    # Логирование старта
    logger.info("Логгер успешно настроен")

def get_logger() -> logger:
    """Получить настроенный логгер"""
    return logger

# Инициализация при импорте
setup_logging(
    log_level=os.getenv("LOG_LEVEL", "INFO"),
    log_dir=Path(os.getenv("LOG_DIR", "logs"))
)