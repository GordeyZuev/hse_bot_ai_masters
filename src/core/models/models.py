from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func


Base = declarative_base()


class Subject(Base):
    __tablename__ = "subjects"

    id = Column(Integer, primary_key=True)
    sheet_subject_id = Column(Integer)
    name = Column(Text, nullable=False)
    year = Column(Integer)
    start_module = Column(Integer)
    end_module = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    is_active = Column(Boolean, default=True)

    # Canonical Google Sheets representation. Legacy link/module columns are kept
    # temporarily so an existing installation can be migrated without downtime.
    modules = Column(ARRAY(SmallInteger), nullable=False, default=list)
    leap_url = Column(Text)
    youtube_url = Column(Text)
    yandex_disk_url = Column(Text)
    is_archived = Column(Boolean, nullable=False, default=False)
    archived_at = Column(DateTime(timezone=True))
    last_synced_at = Column(DateTime(timezone=True))

    wiki_url = Column(Text)
    vk_playlist_url = Column(Text)
    yt_playlist_url = Column(Text)

    tasks = relationship("Task", back_populates="subject", cascade="all, delete-orphan")
    subscriptions = relationship(
        "Subscription", back_populates="subject", cascade="all, delete-orphan"
    )
    chat_topics = relationship(
        "ChatTopic", back_populates="subject", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("name", "year", name="unique_subject"),
        Index(
            "uq_subjects_sheet_subject_id_not_null",
            "sheet_subject_id",
            unique=True,
            postgresql_where=sheet_subject_id.isnot(None),
        ),
        Index("idx_subjects_active_archived", "is_active", "is_archived"),
    )


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True)
    subject_id = Column(
        Integer, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    hw_name = Column(Text)
    source_link = Column(Text)
    soft_deadline_ts = Column(DateTime(timezone=True))
    hard_deadline_ts = Column(DateTime(timezone=True))
    note = Column(Text)
    sheet_row_id = Column(Integer, unique=True)
    source_sheet = Column(Text)
    is_archived = Column(Boolean, nullable=False, default=False)
    archived_at = Column(DateTime(timezone=True))
    last_synced_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    subject = relationship("Subject", back_populates="tasks")
    notifications = relationship(
        "ScheduledNotification", back_populates="task", cascade="all, delete-orphan"
    )
    chat_notifications = relationship(
        "ChatScheduledNotification", back_populates="task", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_tasks_subject_id", "subject_id"),
        Index("idx_tasks_soft_ts", "soft_deadline_ts"),
        Index("idx_tasks_hard_ts", "hard_deadline_ts"),
        Index("idx_tasks_source_archived", "source_sheet", "is_archived"),
    )


class User(Base):
    __tablename__ = "users"

    tg_user_id = Column(BigInteger, primary_key=True)
    first_name = Column(Text)
    last_name = Column(Text)
    username = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_activity = Column(DateTime(timezone=True))
    timezone = Column(
        Text, nullable=False, default="Europe/Moscow", server_default="Europe/Moscow"
    )
    is_active = Column(Boolean, nullable=False, default=True)

    subscriptions = relationship(
        "Subscription", back_populates="user", cascade="all, delete-orphan"
    )
    notifications = relationship(
        "ScheduledNotification", back_populates="user", cascade="all, delete-orphan"
    )
    notification_settings = relationship(
        "UserNotificationSettings",
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )


class UserActionEvent(Base):
    """Small, privacy-conscious product event stream for historical analytics."""

    __tablename__ = "user_action_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    event_name = Column(Text, nullable=False)
    surface = Column(Text)
    chat_id = Column(BigInteger)
    message_id = Column(BigInteger)
    outcome = Column(Text)
    subject_id = Column(Integer)
    task_id = Column(Integer)
    details = Column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    occurred_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_user_action_events_user_time", "user_id", "occurred_at"),
        Index("ix_user_action_events_name_time", "event_name", "occurred_at"),
        Index("ix_user_action_events_chat_time", "chat_id", "occurred_at"),
        Index("ix_user_action_events_occurred_at", "occurred_at"),
    )


class UserNotificationSettings(Base):
    __tablename__ = "user_notification_settings"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        BigInteger, ForeignKey("users.tg_user_id", ondelete="CASCADE"), nullable=False
    )

    reminder1_offset = Column(Integer, nullable=False, default=7)
    reminder1_unit = Column(Text, nullable=False, default="days")

    reminder2_offset = Column(Integer, nullable=False, default=1)
    reminder2_unit = Column(Text, nullable=False, default="days")

    is_active = Column(Boolean, nullable=False, default=True)

    enable_deadline_update_notifications = Column(Boolean, nullable=False, default=True)
    sleep_start_time = Column(Time, nullable=True)
    sleep_end_time = Column(Time, nullable=True)
    display_mode = Column(
        Text, nullable=False, default="compact", server_default="compact"
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_modified = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="notification_settings")

    __table_args__ = (
        UniqueConstraint("user_id", name="unique_user_settings"),
        CheckConstraint("reminder1_offset >= 0", name="check_reminder1_positive"),
        CheckConstraint("reminder2_offset >= 0", name="check_reminder2_positive"),
        CheckConstraint(
            "reminder1_unit IN ('days', 'hours')", name="check_reminder1_unit_valid"
        ),
        CheckConstraint(
            "reminder2_unit IN ('days', 'hours')", name="check_reminder2_unit_valid"
        ),
        CheckConstraint(
            "display_mode IN ('rich', 'compact')", name="check_display_mode_valid"
        ),
    )


class Subscription(Base):
    __tablename__ = "subscriptions"

    user_id = Column(
        BigInteger, ForeignKey("users.tg_user_id", ondelete="CASCADE"), primary_key=True
    )
    subject_id = Column(
        Integer, ForeignKey("subjects.id", ondelete="CASCADE"), primary_key=True
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="subscriptions")
    subject = relationship("Subject", back_populates="subscriptions")

    __table_args__ = (
        Index("idx_subscriptions_user_id", "user_id"),
        Index("idx_subscriptions_subject_id", "subject_id"),
    )


class ScheduledNotification(Base):
    __tablename__ = "scheduled_notifications"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        BigInteger, ForeignKey("users.tg_user_id", ondelete="CASCADE"), nullable=False
    )
    deadline_id = Column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )

    deadline_type = Column(Text, nullable=False)
    notification_number = Column(Integer, nullable=False)

    original_deadline_ts = Column(DateTime(timezone=True), nullable=False)
    planned_delivery_time = Column(DateTime(timezone=True), nullable=False)

    status = Column(Text, nullable=False, default="scheduled")
    attempt_count = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime(timezone=True))
    claimed_at = Column(DateTime(timezone=True))
    sent_at = Column(DateTime(timezone=True))
    last_error = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="notifications")
    task = relationship("Task", back_populates="notifications")

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "deadline_id",
            "deadline_type",
            "notification_number",
            name="unique_user_deadline_notification",
        ),
        Index("idx_sched_notif_status_time", "status", "planned_delivery_time"),
        Index("idx_sched_notif_user_status", "user_id", "status"),
        Index("idx_sched_notif_deadline", "deadline_id"),
        Index("idx_sched_notif_delivery_time", "planned_delivery_time"),
        CheckConstraint(
            "status IN ('scheduled', 'processing', 'retry', 'sent', 'cancelled', 'dead')",
            name="check_status_valid",
        ),
        CheckConstraint(
            "notification_number IN (1, 2)", name="check_notif_number_valid"
        ),
        CheckConstraint(
            "deadline_type IN ('soft', 'hard')", name="check_deadline_type_valid"
        ),
    )


class ChatGroup(Base):
    """Основная таблица чатов (метаданные)"""

    __tablename__ = "chat_groups"

    chat_id = Column(BigInteger, primary_key=True)
    mode = Column(Text, nullable=False)  # 'single' или 'multi'
    chat_title = Column(Text, nullable=True)  # Название чата (кеш)
    chat_type = Column(Text, nullable=False)  # 'group' или 'supergroup'
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    topics = relationship(
        "ChatTopic", back_populates="chat_group", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "chat_type IN ('group', 'supergroup')", name="check_chat_type_valid"
        ),
        CheckConstraint("mode IN ('single', 'multi')", name="check_chat_mode_valid"),
    )


class ChatTopic(Base):
    """Таблица топиков чатов (настройки для каждого топика)"""

    __tablename__ = "chat_group_topics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(
        BigInteger,
        ForeignKey("chat_groups.chat_id", ondelete="CASCADE"),
        nullable=False,
    )
    topic_id = Column(
        BigInteger, nullable=True
    )  # None = общий чат (только в single-mode), число = топик
    topic_title = Column(Text, nullable=True)  # Отображаемое имя топика (кеш)
    subject_id = Column(
        Integer, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )

    # Настройки уведомлений (аналогично UserNotificationSettings)
    reminder1_offset = Column(Integer, nullable=False, default=7)
    reminder1_unit = Column(Text, nullable=False, default="days")
    reminder2_offset = Column(Integer, nullable=False, default=1)
    reminder2_unit = Column(Text, nullable=False, default="days")
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    chat_group = relationship("ChatGroup", back_populates="topics")
    subject = relationship("Subject", back_populates="chat_topics")
    notifications = relationship(
        "ChatScheduledNotification",
        back_populates="chat_topic",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("chat_id", "topic_id", name="unique_chat_topic"),
        Index(
            "uq_chat_group_topics_single_mode",
            "chat_id",
            unique=True,
            postgresql_where=topic_id.is_(None),
        ),
        CheckConstraint(
            "reminder1_unit IN ('days', 'hours')",
            name="check_topic_reminder1_unit_valid",
        ),
        CheckConstraint(
            "reminder2_unit IN ('days', 'hours')",
            name="check_topic_reminder2_unit_valid",
        ),
        CheckConstraint("reminder1_offset >= 0", name="check_topic_reminder1_positive"),
        CheckConstraint("reminder2_offset >= 0", name="check_topic_reminder2_positive"),
    )


class ChatScheduledNotification(Base):
    __tablename__ = "chat_scheduled_notifications"

    id = Column(Integer, primary_key=True)
    chat_topic_id = Column(
        Integer, ForeignKey("chat_group_topics.id", ondelete="CASCADE"), nullable=False
    )
    chat_id = Column(
        BigInteger,
        nullable=False,  # Для удобства группировки, не FK
    )
    topic_id = Column(
        BigInteger,
        nullable=True,  # Для удобства, не FK
    )
    deadline_id = Column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )

    deadline_type = Column(Text, nullable=False)
    notification_number = Column(Integer, nullable=False)

    original_deadline_ts = Column(DateTime(timezone=True), nullable=False)
    planned_delivery_time = Column(DateTime(timezone=True), nullable=False)

    status = Column(Text, nullable=False, default="scheduled")
    attempt_count = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime(timezone=True))
    claimed_at = Column(DateTime(timezone=True))
    sent_at = Column(DateTime(timezone=True))
    last_error = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    chat_topic = relationship("ChatTopic", back_populates="notifications")
    task = relationship("Task", back_populates="chat_notifications")

    __table_args__ = (
        UniqueConstraint(
            "chat_topic_id",
            "deadline_id",
            "deadline_type",
            "notification_number",
            name="unique_chat_topic_deadline_notification",
        ),
        Index("idx_chat_sched_notif_status_time", "status", "planned_delivery_time"),
        Index("idx_chat_sched_notif_topic_status", "chat_topic_id", "status"),
        Index("idx_chat_sched_notif_deadline", "deadline_id"),
        Index("idx_chat_sched_notif_delivery_time", "planned_delivery_time"),
        CheckConstraint(
            "status IN ('scheduled', 'processing', 'retry', 'sent', 'cancelled', 'dead')",
            name="check_chat_status_valid",
        ),
        CheckConstraint(
            "notification_number IN (1, 2)", name="check_chat_notif_number_valid"
        ),
        CheckConstraint(
            "deadline_type IN ('soft', 'hard')", name="check_chat_deadline_type_valid"
        ),
    )


class TaskUserStatus(Base):
    __tablename__ = "task_user_status"

    user_id = Column(
        BigInteger, ForeignKey("users.tg_user_id", ondelete="CASCADE"), primary_key=True
    )
    deadline_id = Column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )

    __table_args__ = (Index("ix_tus_deadline_id", "deadline_id"),)
