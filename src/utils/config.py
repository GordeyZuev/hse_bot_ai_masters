"""
Конфигурация приложения с использованием Pydantic Settings.
"""
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings
import os
from pathlib import Path

# Получаем путь к корневой директории проекта
ROOT_DIR = Path(__file__).parent.parent.parent
CONFIG_DIR = ROOT_DIR / "config"


class Settings(BaseSettings):
    """Настройки приложения."""
    
    # Telegram Bot Configuration
    bot_token: str = Field(..., env="BOT_TOKEN")
    webhook_url: Optional[str] = Field(None, env="WEBHOOK_URL")
    webhook_path: str = Field("/webhook", env="WEBHOOK_PATH")
    
    # Database Configuration
    database_url: str = Field(..., env="DATABASE_URL")
    db_host: str = Field("localhost", env="DB_HOST")
    db_port: int = Field(5432, env="DB_PORT")
    db_name: str = Field("hse_bot_db", env="DB_NAME")
    db_user: str = Field("postgres", env="DB_USER")
    db_password: str = Field("password", env="DB_PASSWORD")
    
    # Redis Configuration
    redis_url: str = Field("redis://localhost:6379/0", env="REDIS_URL")
    redis_host: str = Field("localhost", env="REDIS_HOST")
    redis_port: int = Field(6379, env="REDIS_PORT")
    redis_db: int = Field(0, env="REDIS_DB")
    
    # Google Sheets Configuration
    google_sheets_url: str = Field(..., env="GOOGLE_SHEETS_URL")
    google_creds_file: str = Field("config/creds.json", env="GOOGLE_CREDS_FILE")
    
    # Application Configuration
    debug: bool = Field(False, env="DEBUG")
    log_level: str = Field("INFO", env="LOG_LEVEL")
    timezone: str = Field("Europe/Moscow", env="TIMEZONE")
    
    # Notification Settings
    max_notifications_per_user: int = Field(2, env="MAX_NOTIFICATIONS_PER_USER")
    default_first_notification_hours: int = Field(24, env="DEFAULT_FIRST_NOTIFICATION_HOURS")
    default_second_notification_hours: int = Field(2, env="DEFAULT_SECOND_NOTIFICATION_HOURS")
    notification_batch_size: int = Field(50, env="NOTIFICATION_BATCH_SIZE")
    notification_retry_attempts: int = Field(3, env="NOTIFICATION_RETRY_ATTEMPTS")
    
    # Rate Limiting
    telegram_rate_limit: int = Field(30, env="TELEGRAM_RATE_LIMIT")
    google_sheets_rate_limit: int = Field(100, env="GOOGLE_SHEETS_RATE_LIMIT")
    
    # Monitoring
    health_check_interval: int = Field(300, env="HEALTH_CHECK_INTERVAL")
    
    class Config:
        env_file = CONFIG_DIR / ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
    
    @property
    def google_creds_path(self) -> Path:
        """Возвращает полный путь к файлу с credentials для Google API."""
        if os.path.isabs(self.google_creds_file):
            return Path(self.google_creds_file)
        return ROOT_DIR / self.google_creds_file
    
    @property
    def logs_dir(self) -> Path:
        """Возвращает путь к директории с логами."""
        logs_dir = ROOT_DIR / "logs"
        logs_dir.mkdir(exist_ok=True)
        return logs_dir


# Создаем глобальный экземпляр настроек
settings = Settings()


def get_settings() -> Settings:
    """Возвращает экземпляр настроек приложения."""
    return settings