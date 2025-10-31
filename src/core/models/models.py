from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func


Base = declarative_base()


class Subject(Base):
    __tablename__ = "subjects"

    id = Column(Integer, primary_key=True)
    # ID из Google Sheets для листа "Дисциплины" (может отсутствовать у старых записей)
    sheet_subject_id = Column(Integer)
    name = Column(Text, nullable=False)
    year = Column(Integer)
    start_module = Column(Integer)
    end_module = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)

    # Ссылки на ресурсы
    wiki_url = Column(Text)
    vk_playlist_url = Column(Text)
    yt_playlist_url = Column(Text)

    deadlines = relationship(
        "Deadline", back_populates="subject", cascade="all, delete-orphan"
    )
    subscriptions = relationship(
        "Subscription", back_populates="subject", cascade="all, delete-orphan"
    )
    chat_groups = relationship(
        "ChatGroup", back_populates="subject", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("name", "year", name="unique_subject"),
    )


class Deadline(Base):
    __tablename__ = "deadlines"

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
    last_updated = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    subject = relationship("Subject", back_populates="deadlines")
    notifications = relationship(
        "ScheduledNotification", back_populates="deadline", cascade="all, delete-orphan"
    )
    chat_notifications = relationship(
        "ChatScheduledNotification", back_populates="deadline", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_deadlines_subject_id", "subject_id"),
        Index("idx_deadlines_soft_ts", "soft_deadline_ts"),
        Index("idx_deadlines_hard_ts", "hard_deadline_ts"),
    )


class User(Base):
    __tablename__ = "users"

    tg_user_id = Column(BigInteger, primary_key=True)
    first_name = Column(Text)
    last_name = Column(Text)
    username = Column(Text)
    subscribed_at = Column(DateTime(timezone=True), server_default=func.now())
    last_activity_ts = Column(DateTime(timezone=True))
    timezone = Column(
        Text, nullable=False, default="Europe/Moscow", server_default="Europe/Moscow"
    )
    settings_version = Column(Integer, default=1)
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
        Integer, ForeignKey("deadlines.id", ondelete="CASCADE"), nullable=False
    )

    deadline_type = Column(Text, nullable=False)
    notification_number = Column(Integer, nullable=False)

    original_deadline_ts = Column(DateTime(timezone=True), nullable=False)
    planned_delivery_time = Column(DateTime(timezone=True), nullable=False)

    status = Column(Text, nullable=False, default="scheduled")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="notifications")
    deadline = relationship("Deadline", back_populates="notifications")

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
            "status IN ('scheduled', 'sent', 'cancelled', 'failed')",
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
    __tablename__ = "chat_groups"

    chat_id = Column(BigInteger, primary_key=True)
    topic_id = Column(BigInteger, nullable=True)  # None = общий чат, число = топик
    topic_title = Column(Text, nullable=True)  # Отображаемое имя топика (кеш)
    chat_type = Column(Text, nullable=False)  # 'group' или 'supergroup'
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

    subject = relationship("Subject", back_populates="chat_groups")
    notifications = relationship(
        "ChatScheduledNotification", back_populates="chat_group", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "chat_type IN ('group', 'supergroup')",
            name="check_chat_type_valid"
        ),
        CheckConstraint(
            "reminder1_unit IN ('days', 'hours')",
            name="check_chat_reminder1_unit_valid"
        ),
        CheckConstraint(
            "reminder2_unit IN ('days', 'hours')",
            name="check_chat_reminder2_unit_valid"
        ),
        CheckConstraint("reminder1_offset >= 0", name="check_chat_reminder1_positive"),
        CheckConstraint("reminder2_offset >= 0", name="check_chat_reminder2_positive"),
    )


class ChatScheduledNotification(Base):
    __tablename__ = "chat_scheduled_notifications"

    id = Column(Integer, primary_key=True)
    chat_group_id = Column(
        BigInteger, ForeignKey("chat_groups.chat_id", ondelete="CASCADE"), nullable=False
    )
    deadline_id = Column(
        Integer, ForeignKey("deadlines.id", ondelete="CASCADE"), nullable=False
    )

    deadline_type = Column(Text, nullable=False)
    notification_number = Column(Integer, nullable=False)

    original_deadline_ts = Column(DateTime(timezone=True), nullable=False)
    planned_delivery_time = Column(DateTime(timezone=True), nullable=False)

    status = Column(Text, nullable=False, default="scheduled")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    chat_group = relationship("ChatGroup", back_populates="notifications")
    deadline = relationship("Deadline", back_populates="chat_notifications")

    __table_args__ = (
        UniqueConstraint(
            "chat_group_id",
            "deadline_id",
            "deadline_type",
            "notification_number",
            name="unique_chat_deadline_notification",
        ),
        Index("idx_chat_sched_notif_status_time", "status", "planned_delivery_time"),
        Index("idx_chat_sched_notif_chat_status", "chat_group_id", "status"),
        Index("idx_chat_sched_notif_deadline", "deadline_id"),
        Index("idx_chat_sched_notif_delivery_time", "planned_delivery_time"),
        CheckConstraint(
            "status IN ('scheduled', 'sent', 'cancelled', 'failed')",
            name="check_chat_status_valid",
        ),
        CheckConstraint(
            "notification_number IN (1, 2)",
            name="check_chat_notif_number_valid"
        ),
        CheckConstraint(
            "deadline_type IN ('soft', 'hard')",
            name="check_chat_deadline_type_valid"
        ),
    )
