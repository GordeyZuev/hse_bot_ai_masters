from loguru import logger
from datetime import datetime
from pathlib import Path
import sys

# Создаем директорию для логов
LOG_DIR = Path('logs')
LOG_DIR.mkdir(exist_ok=True)

def setup_logger():
    """Настройка логгера с консольным выводом и файловым логированием"""
    logger.remove()
    
    # Общие параметры для файловых логов
    file_config = {
        "rotation": "10 MB",
        "retention": "7 days", 
        "compression": "zip",
        "format": "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
    }
    
    current_date = datetime.now().strftime("%d-%m-%Y")
    
    # Консольный вывод
    logger.add(sys.stderr, 
              format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {message}",
              level="INFO", colorize=True)
    
    # Общий лог файл
    logger.add(LOG_DIR / f"bot_{current_date}.log", level="INFO", **file_config)
    
    # Файл только для ошибок
    logger.add(LOG_DIR / f"bot_{current_date}_error.log", level="ERROR", **file_config)
    
    return logger

# Инициализируем логгер
logger = setup_logger()