"""
Модели базы данных для телеграм бота HSE.
"""
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import (
    BigInteger, String, DateTime, Boolean, Integer, 
    Text, ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

Base = declarative_base()


class User(Base):
    """Модель пользователя телеграм бота."""
    
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    language_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, default="ru")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    last_activity: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    subscriptions: Mapped[List["Subscription"]] = relationship(
        "Subscription", back_populates="user", cascade="all, delete-orphan"
    )
    notification_settings: Mapped[Optional["NotificationSettings"]] = relationship(
        "NotificationSettings", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    sent_notifications: Mapped[List["SentNotification"]] = relationship(
        "SentNotification", back_populates="user", cascade="all, delete-orphan"
    )
    
    def __repr__(self) -> str:
        return f"<User(id={self.id}, telegram_id={self.telegram_id}, username='{self.username}')>"


class Subject(Base):
    """Модель дисциплины."""
    
    __tablename__ = "subjects"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    
    # Relationships
    subscriptions: Mapped[List["Subscription"]] = relationship(
        "Subscription", back_populates="subject", cascade="all, delete-orphan"
    )
    deadlines: Mapped[List["Deadline"]] = relationship(
        "Deadline", back_populates="subject", cascade="all, delete-orphan"
    )
    
    def __repr__(self) -> str:
        return f"<Subject(id={self.id}, name='{self.name}')>"


class Subscription(Base):
    """Модель подписки пользователя на дисциплину."""
    
    __tablename__ = "subscriptions"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    subject_id: Mapped[int] = mapped_column(Integer, ForeignKey("subjects.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="subscriptions")
    subject: Mapped["Subject"] = relationship("Subject", back_populates="subscriptions")
    
    # Constraints
    __table_args__ = (
        UniqueConstraint("user_id", "subject_id", name="unique_user_subject_subscription"),
        Index("idx_subscription_user_active", "user_id", "is_active"),
        Index("idx_subscription_subject_active", "subject_id", "is_active"),
    )
    
    def __repr__(self) -> str:
        return f"<Subscription(id={self.id}, user_id={self.user_id}, subject_id={self.subject_id})>"


class NotificationSettings(Base):
    """Модель настроек уведомлений пользователя."""
    
    __tablename__ = "notification_settings"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notifications_count: Mapped[int] = mapped_column(Integer, default=2, nullable=False)  # 1 или 2
    first_notification_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)  # За сколько часов до дедлайна
    second_notification_hours: Mapped[int] = mapped_column(Integer, default=2, nullable=False)  # За сколько часов до дедлайна
    timezone: Mapped[str] = mapped_column(String(50), default="Europe/Moscow", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="notification_settings")
    
    def __repr__(self) -> str:
        return f"<NotificationSettings(id={self.id}, user_id={self.user_id}, count={self.notifications_count})>"


class Deadline(Base):
    """Модель дедлайна (кеш данных из Google Sheets)."""
    
    __tablename__ = "deadlines"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)  # ID из Google Sheets
    subject_id: Mapped[int] = mapped_column(Integer, ForeignKey("subjects.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_link: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    soft_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    hard_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    days_until: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Вычисляемое поле
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    
    # Relationships
    subject: Mapped["Subject"] = relationship("Subject", back_populates="deadlines")
    sent_notifications: Mapped[List["SentNotification"]] = relationship(
        "SentNotification", back_populates="deadline", cascade="all, delete-orphan"
    )
    
    # Indexes
    __table_args__ = (
        Index("idx_deadline_subject_active", "subject_id", "is_active"),
        Index("idx_deadline_hard_deadline", "hard_deadline"),
        Index("idx_deadline_external_id", "external_id"),
    )
    
    def __repr__(self) -> str:
        return f"<Deadline(id={self.id}, title='{self.title}', hard_deadline={self.hard_deadline})>"


class SentNotification(Base):
    """Модель отправленного уведомления."""
    
    __tablename__ = "sent_notifications"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    deadline_id: Mapped[int] = mapped_column(Integer, ForeignKey("deadlines.id"), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)  # 'first', 'second', 'urgent'
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)  # ID сообщения в Telegram
    status: Mapped[str] = mapped_column(String(50), default="sent", nullable=False)  # 'sent', 'delivered', 'failed', 'blocked'
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="sent_notifications")
    deadline: Mapped["Deadline"] = relationship("Deadline", back_populates="sent_notifications")
    
    # Constraints and Indexes
    __table_args__ = (
        UniqueConstraint("user_id", "deadline_id", "notification_type", name="unique_user_deadline_notification"),
        Index("idx_sent_notification_user_status", "user_id", "status"),
        Index("idx_sent_notification_deadline_type", "deadline_id", "notification_type"),
        Index("idx_sent_notification_sent_at", "sent_at"),
    )
    
    def __repr__(self) -> str:
        return f"<SentNotification(id={self.id}, user_id={self.user_id}, deadline_id={self.deadline_id}, type='{self.notification_type}')>"