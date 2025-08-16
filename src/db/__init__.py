"""
Модуль для работы с базой данных.
"""
from .models import (
    Base,
    User,
    Subject,
    Subscription,
    NotificationSettings,
    Deadline,
    SentNotification,
)
from .session import (
    engine,
    AsyncSessionLocal,
    get_db_session,
    create_tables,
    drop_tables,
    close_db,
    DatabaseManager,
    db_manager,
)
from .crud import (
    UserCRUD,
    SubjectCRUD,
    SubscriptionCRUD,
    NotificationSettingsCRUD,
    DeadlineCRUD,
    SentNotificationCRUD,
)

__all__ = [
    # Models
    "Base",
    "User",
    "Subject",
    "Subscription",
    "NotificationSettings",
    "Deadline",
    "SentNotification",
    # Session
    "engine",
    "AsyncSessionLocal",
    "get_db_session",
    "create_tables",
    "drop_tables",
    "close_db",
    "DatabaseManager",
    "db_manager",
    # CRUD
    "UserCRUD",
    "SubjectCRUD",
    "SubscriptionCRUD",
    "NotificationSettingsCRUD",
    "DeadlineCRUD",
    "SentNotificationCRUD",
]