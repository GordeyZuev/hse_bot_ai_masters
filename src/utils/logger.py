"""
Система логирования для телеграм бота HSE на основе Loguru.
"""
import sys
from pathlib import Path
from typing import Optional
from loguru import logger
from datetime import datetime

from .config import get_settings

settings = get_settings()


def setup_logging(
    log_level: Optional[str] = None,
    log_file: Optional[str] = None,
    enable_json: bool = False
) -> None:
    """
    Настраивает систему логирования с использованием Loguru.
    
    Args:
        log_level: Уровень логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Путь к файлу логов (опционально)
        enable_json: Включить JSON формат логов
    """
    log_level = log_level or settings.log_level
    
    # Удаляем стандартный хендлер
    logger.remove()
    
    # Консольный хендлер с цветным выводом
    console_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )
    
    logger.add(
        sys.stdout,
        format=console_format,
        level=log_level,
        colorize=True,
        backtrace=True,
        diagnose=True,
    )
    
    # Файловый хендлер
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        if enable_json:
            # JSON формат для продакшена
            logger.add(
                log_file,
                format="{time} | {level} | {name}:{function}:{line} | {message}",
                level=log_level,
                rotation="1 day",
                retention="30 days",
                compression="gz",
                serialize=True,  # JSON формат
                backtrace=True,
                diagnose=True,
            )
        else:
            # Обычный формат для разработки
            file_format = (
                "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
                "{level: <8} | "
                "{name}:{function}:{line} | "
                "{message}"
            )
            
            logger.add(
                log_file,
                format=file_format,
                level=log_level,
                rotation="1 day",
                retention="30 days",
                compression="gz",
                backtrace=True,
                diagnose=True,
            )
    
    # Настройка уровней для внешних библиотек
    import logging
    logging.getLogger("aiogram").setLevel(logging.INFO)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logging.getLogger("gspread").setLevel(logging.INFO)


def get_logger(name: str):
    """
    Получает логгер с указанным именем.
    
    Args:
        name: Имя логгера (обычно __name__)
    
    Returns:
        Loguru логгер с контекстом
    """
    return logger.bind(name=name)


class BotLogger:
    """Специализированный логгер для бота с дополнительными методами."""
    
    def __init__(self, name: str):
        self.logger = get_logger(name)
        self.name = name
    
    def user_action(self, user_id: int, action: str, **kwargs):
        """Логирует действие пользователя."""
        self.logger.info(
            "User action: {action}",
            action=action,
            user_id=user_id,
            **kwargs
        )
    
    def notification_sent(self, user_id: int, deadline_id: int, notification_type: str, status: str, **kwargs):
        """Логирует отправку уведомления."""
        self.logger.info(
            "Notification sent: {notification_type} to user {user_id}, status: {status}",
            user_id=user_id,
            deadline_id=deadline_id,
            notification_type=notification_type,
            status=status,
            **kwargs
        )
    
    def notification_failed(self, user_id: int, deadline_id: int, error: str, **kwargs):
        """Логирует ошибку отправки уведомления."""
        self.logger.error(
            "Notification failed for user {user_id}: {error}",
            user_id=user_id,
            deadline_id=deadline_id,
            error=error,
            **kwargs
        )
    
    def sheets_sync(self, created: int, updated: int, errors: int = 0, **kwargs):
        """Логирует синхронизацию с Google Sheets."""
        self.logger.info(
            "Google Sheets sync completed: {created} created, {updated} updated, {errors} errors",
            created=created,
            updated=updated,
            errors=errors,
            **kwargs
        )
    
    def database_error(self, operation: str, error: str, **kwargs):
        """Логирует ошибку базы данных."""
        self.logger.error(
            "Database error in {operation}: {error}",
            operation=operation,
            error=error,
            **kwargs
        )
    
    def api_error(self, api: str, method: str, error: str, **kwargs):
        """Логирует ошибку API."""
        self.logger.error(
            "API error in {api}.{method}: {error}",
            api=api,
            method=method,
            error=error,
            **kwargs
        )
    
    def debug(self, message: str, **kwargs):
        """Debug уровень логирования."""
        self.logger.debug(message, **kwargs)
    
    def info(self, message: str, **kwargs):
        """Info уровень логирования."""
        self.logger.info(message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        """Warning уровень логирования."""
        self.logger.warning(message, **kwargs)
    
    def error(self, message: str, **kwargs):
        """Error уровень логирования."""
        self.logger.error(message, **kwargs)
    
    def critical(self, message: str, **kwargs):
        """Critical уровень логирования."""
        self.logger.critical(message, **kwargs)
    
    def exception(self, message: str, **kwargs):
        """Логирует исключение с трейсбеком."""
        self.logger.exception(message, **kwargs)


# Инициализация логирования при импорте модуля
def init_logging():
    """Инициализирует систему логирования с настройками по умолчанию."""
    log_file = settings.logs_dir / f"hse_bot_{datetime.now().strftime('%Y%m%d')}.log"
    setup_logging(
        log_level=settings.log_level,
        log_file=str(log_file),
        enable_json=not settings.debug
    )


# Создаем основные логгеры
def create_loggers():
    """Создает основные логгеры для приложения."""
    return {
        'main': BotLogger('hse_bot.main'),
        'bot': BotLogger('hse_bot.bot'),
        'db': BotLogger('hse_bot.database'),
        'sheets': BotLogger('hse_bot.sheets'),
        'notifications': BotLogger('hse_bot.notifications'),
        'scheduler': BotLogger('hse_bot.scheduler'),
    }


# Декоратор для логирования выполнения функций
def log_execution(logger_instance: BotLogger):
    """
    Декоратор для автоматического логирования выполнения функций.
    
    Args:
        logger_instance: Экземпляр BotLogger для логирования
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            logger_instance.debug(f"Executing {func.__name__} with args={args}, kwargs={kwargs}")
            try:
                result = func(*args, **kwargs)
                logger_instance.debug(f"Successfully executed {func.__name__}")
                return result
            except Exception as e:
                logger_instance.error(f"Error in {func.__name__}: {str(e)}")
                raise
        return wrapper
    return decorator


# Асинхронный декоратор для логирования
def log_async_execution(logger_instance: BotLogger):
    """
    Декоратор для автоматического логирования выполнения асинхронных функций.
    
    Args:
        logger_instance: Экземпляр BotLogger для логирования
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            logger_instance.debug(f"Executing async {func.__name__} with args={args}, kwargs={kwargs}")
            try:
                result = await func(*args, **kwargs)
                logger_instance.debug(f"Successfully executed async {func.__name__}")
                return result
            except Exception as e:
                logger_instance.error(f"Error in async {func.__name__}: {str(e)}")
                raise
        return wrapper
    return decorator


# Инициализируем логирование
init_logging()

# Создаем основные логгеры
loggers = create_loggers()

# Экспортируем основные логгеры для удобства
main_logger = loggers['main']
bot_logger = loggers['bot']
db_logger = loggers['db']
sheets_logger = loggers['sheets']
notifications_logger = loggers['notifications']
scheduler_logger = loggers['scheduler']

# Основной логгер для обратной совместимости
main_log = logger.bind(name="hse_bot")