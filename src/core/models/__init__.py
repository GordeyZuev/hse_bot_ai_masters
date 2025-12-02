from .models import (
    Base,
    Chat,
    ChatScheduledNotification,
    ChatTopic,
    ScheduledNotification,
    Subject,
    Subscription,
    Task,
    TaskUserStatus,
    User,
    UserNotificationSettings,
)


# Обратная совместимость: ChatGroup как alias для Chat
ChatGroup = Chat


__all__ = [
    "Base",
    "Chat",
    "ChatGroup",  # Для обратной совместимости
    "ChatScheduledNotification",
    "ChatTopic",
    "ScheduledNotification",
    "Subject",
    "Subscription",
    "Task",
    "TaskUserStatus",
    "User",
    "UserNotificationSettings",
]
