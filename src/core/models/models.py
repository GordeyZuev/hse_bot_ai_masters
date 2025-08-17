from sqlalchemy import Column, Integer, BigInteger, Boolean, Text, DateTime, ForeignKey, UniqueConstraint, Index, CheckConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

Base = declarative_base()

class Subject(Base):
    __tablename__ = 'subjects'
    
    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    year = Column(Integer)
    start_module = Column(Integer)  # начальный модуль
    end_module = Column(Integer)  # конечный модуль
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)
    
    deadlines = relationship("Deadline", back_populates="subject", cascade="all, delete-orphan")
    subscriptions = relationship("Subscription", back_populates="subject", cascade="all, delete-orphan")
    
    __table_args__ = (
        UniqueConstraint('name', 'year', name='unique_subject'),
    )

class Deadline(Base):
    __tablename__ = 'deadlines'
    
    id = Column(Integer, primary_key=True)
    subject_id = Column(Integer, ForeignKey('subjects.id', ondelete='CASCADE'), nullable=False)
    hw_name = Column(Text)
    source_link = Column(Text)
    soft_deadline_ts = Column(DateTime(timezone=True))
    hard_deadline_ts = Column(DateTime(timezone=True))
    note = Column(Text)
    sheet_row_id = Column(Integer, unique=True)
    last_updated = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    subject = relationship("Subject", back_populates="deadlines")
    notifications = relationship("NotificationLog", back_populates="deadline", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_deadlines_subject_id', 'subject_id'),
    )

class User(Base):
    __tablename__ = 'users'
    
    tg_user_id = Column(BigInteger, primary_key=True)
    first_name = Column(Text)
    last_name = Column(Text)
    username = Column(Text)
    subscribed_at = Column(DateTime(timezone=True), server_default=func.now())
    last_activity_ts = Column(DateTime(timezone=True))
    timezone = Column(Text, nullable=False, default='Europe/Moscow', server_default='Europe/Moscow')
    
    notifications = relationship("UserNotification", back_populates="user", cascade="all, delete-orphan")
    subscriptions = relationship("Subscription", back_populates="user", cascade="all, delete-orphan")
    notification_logs = relationship("NotificationLog", back_populates="user", cascade="all, delete-orphan")

class UserNotification(Base):
    __tablename__ = 'user_notifications'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.tg_user_id', ondelete='CASCADE'), nullable=False)
    
    offset_value = Column(Integer, nullable=False, default=1)
    offset_unit = Column(Text, nullable=False, default='days')
    is_enabled = Column(Boolean, nullable=False, default=True)
    
    notification_number = Column(Integer, nullable=False)  
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_modified = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    user = relationship("User", back_populates="notifications")
    
    __table_args__ = (
        UniqueConstraint('user_id', 'notification_number', name='unique_user_notification_number'),
        CheckConstraint('offset_value >= 0', name='check_offset_positive'),
        CheckConstraint("offset_unit IN ('days', 'hours', 'minutes')", name='check_offset_unit_valid'),
        CheckConstraint('notification_number IN (1, 2)', name='check_notification_number_valid'),
    )

class Subscription(Base):
    __tablename__ = 'subscriptions'
    
    user_id = Column(BigInteger, ForeignKey('users.tg_user_id', ondelete='CASCADE'), primary_key=True)
    subject_id = Column(Integer, ForeignKey('subjects.id', ondelete='CASCADE'), primary_key=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    user = relationship("User", back_populates="subscriptions")
    subject = relationship("Subject", back_populates="subscriptions")
    
    __table_args__ = (
        Index('idx_subscriptions_user_id', 'user_id'),
        Index('idx_subscriptions_subject_id', 'subject_id'),
    )

class NotificationLog(Base):
    __tablename__ = 'notification_log'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.tg_user_id', ondelete='CASCADE'), nullable=False)
    deadline_id = Column(Integer, ForeignKey('deadlines.id', ondelete='CASCADE'), nullable=False)
    notification_type = Column(Text, nullable=False)
    scheduled_for = Column(DateTime(timezone=True), nullable=False)
    status = Column(Text, nullable=False, default='scheduled')
    attempt_count = Column(Integer, nullable=False, default=0)
    sent_at = Column(DateTime(timezone=True))
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    user = relationship("User", back_populates="notification_logs")
    deadline = relationship("Deadline", back_populates="notifications")
    
    __table_args__ = (
        UniqueConstraint('user_id', 'deadline_id', 'notification_type', name='unique_notification_task'),
        Index('idx_notification_log_status_scheduled', 'status', 'scheduled_for'),
        Index('idx_notification_log_user_id', 'user_id'),
    )