"""
CRUD операции для работы с базой данных.
"""
from datetime import datetime, timezone
from typing import List, Optional, Sequence
from sqlalchemy import select, update, delete, and_, or_, desc, asc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload

from .models import (
    User, Subject, Subscription, NotificationSettings, 
    Deadline, SentNotification
)


class UserCRUD:
    """CRUD операции для пользователей."""
    
    @staticmethod
    async def create(
        session: AsyncSession,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        language_code: Optional[str] = "ru"
    ) -> User:
        """Создает нового пользователя."""
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            language_code=language_code,
            last_activity=datetime.now(timezone.utc)
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user
    
    @staticmethod
    async def get_by_telegram_id(session: AsyncSession, telegram_id: int) -> Optional[User]:
        """Получает пользователя по Telegram ID."""
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_by_id(session: AsyncSession, user_id: int) -> Optional[User]:
        """Получает пользователя по ID."""
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_all_active(session: AsyncSession) -> List[User]:
        """Получает всех активных пользователей."""
        result = await session.execute(
            select(User).where(and_(User.is_active == True, User.is_blocked == False))
        )
        return list(result.scalars().all())
    
    @staticmethod
    async def update_activity(session: AsyncSession, telegram_id: int) -> Optional[User]:
        """Обновляет время последней активности пользователя."""
        result = await session.execute(
            update(User)
            .where(User.telegram_id == telegram_id)
            .values(last_activity=datetime.now(timezone.utc))
            .returning(User)
        )
        await session.commit()
        return result.scalar_one_or_none()
    
    @staticmethod
    async def set_blocked(session: AsyncSession, telegram_id: int, is_blocked: bool = True) -> Optional[User]:
        """Помечает пользователя как заблокированного."""
        result = await session.execute(
            update(User)
            .where(User.telegram_id == telegram_id)
            .values(is_blocked=is_blocked)
            .returning(User)
        )
        await session.commit()
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_or_create(
        session: AsyncSession,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        language_code: Optional[str] = "ru"
    ) -> tuple[User, bool]:
        """Получает пользователя или создает нового. Возвращает (user, created)."""
        user = await UserCRUD.get_by_telegram_id(session, telegram_id)
        if user:
            # Обновляем информацию о пользователе
            if username != user.username or first_name != user.first_name or last_name != user.last_name:
                await session.execute(
                    update(User)
                    .where(User.telegram_id == telegram_id)
                    .values(
                        username=username,
                        first_name=first_name,
                        last_name=last_name,
                        last_activity=datetime.now(timezone.utc)
                    )
                )
                await session.commit()
                await session.refresh(user)
            else:
                await UserCRUD.update_activity(session, telegram_id)
            return user, False
        else:
            user = await UserCRUD.create(session, telegram_id, username, first_name, last_name, language_code)
            return user, True


class SubjectCRUD:
    """CRUD операции для дисциплин."""
    
    @staticmethod
    async def create(session: AsyncSession, name: str, description: Optional[str] = None) -> Subject:
        """Создает новую дисциплину."""
        subject = Subject(name=name, description=description)
        session.add(subject)
        await session.commit()
        await session.refresh(subject)
        return subject
    
    @staticmethod
    async def get_by_id(session: AsyncSession, subject_id: int) -> Optional[Subject]:
        """Получает дисциплину по ID."""
        result = await session.execute(
            select(Subject).where(Subject.id == subject_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_by_name(session: AsyncSession, name: str) -> Optional[Subject]:
        """Получает дисциплину по названию."""
        result = await session.execute(
            select(Subject).where(Subject.name == name)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_all_active(session: AsyncSession) -> List[Subject]:
        """Получает все активные дисциплины."""
        result = await session.execute(
            select(Subject).where(Subject.is_active == True).order_by(Subject.name)
        )
        return list(result.scalars().all())
    
    @staticmethod
    async def get_or_create(session: AsyncSession, name: str, description: Optional[str] = None) -> tuple[Subject, bool]:
        """Получает дисциплину или создает новую. Возвращает (subject, created)."""
        subject = await SubjectCRUD.get_by_name(session, name)
        if subject:
            return subject, False
        else:
            subject = await SubjectCRUD.create(session, name, description)
            return subject, True


class SubscriptionCRUD:
    """CRUD операции для подписок."""
    
    @staticmethod
    async def create(session: AsyncSession, user_id: int, subject_id: int) -> Subscription:
        """Создает новую подписку."""
        subscription = Subscription(user_id=user_id, subject_id=subject_id)
        session.add(subscription)
        await session.commit()
        await session.refresh(subscription)
        return subscription
    
    @staticmethod
    async def get_by_user_and_subject(
        session: AsyncSession, 
        user_id: int, 
        subject_id: int
    ) -> Optional[Subscription]:
        """Получает подписку по пользователю и дисциплине."""
        result = await session.execute(
            select(Subscription).where(
                and_(
                    Subscription.user_id == user_id,
                    Subscription.subject_id == subject_id
                )
            )
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_user_subscriptions(
        session: AsyncSession, 
        user_id: int, 
        active_only: bool = True
    ) -> List[Subscription]:
        """Получает все подписки пользователя."""
        query = select(Subscription).options(joinedload(Subscription.subject)).where(
            Subscription.user_id == user_id
        )
        if active_only:
            query = query.where(Subscription.is_active == True)
        
        result = await session.execute(query)
        return list(result.scalars().all())
    
    @staticmethod
    async def get_subject_subscribers(
        session: AsyncSession, 
        subject_id: int, 
        active_only: bool = True
    ) -> List[Subscription]:
        """Получает всех подписчиков дисциплины."""
        query = select(Subscription).options(joinedload(Subscription.user)).where(
            Subscription.subject_id == subject_id
        )
        if active_only:
            query = query.where(
                and_(
                    Subscription.is_active == True,
                    Subscription.user.has(and_(User.is_active == True, User.is_blocked == False))
                )
            )
        
        result = await session.execute(query)
        return list(result.scalars().all())
    
    @staticmethod
    async def subscribe(session: AsyncSession, user_id: int, subject_id: int) -> Subscription:
        """Подписывает пользователя на дисциплину."""
        subscription = await SubscriptionCRUD.get_by_user_and_subject(session, user_id, subject_id)
        if subscription:
            if not subscription.is_active:
                await session.execute(
                    update(Subscription)
                    .where(Subscription.id == subscription.id)
                    .values(is_active=True, updated_at=datetime.now(timezone.utc))
                )
                await session.commit()
                await session.refresh(subscription)
            return subscription
        else:
            return await SubscriptionCRUD.create(session, user_id, subject_id)
    
    @staticmethod
    async def unsubscribe(session: AsyncSession, user_id: int, subject_id: int) -> bool:
        """Отписывает пользователя от дисциплины."""
        result = await session.execute(
            update(Subscription)
            .where(
                and_(
                    Subscription.user_id == user_id,
                    Subscription.subject_id == subject_id
                )
            )
            .values(is_active=False, updated_at=datetime.now(timezone.utc))
        )
        await session.commit()
        return result.rowcount > 0


class NotificationSettingsCRUD:
    """CRUD операции для настроек уведомлений."""
    
    @staticmethod
    async def create(
        session: AsyncSession,
        user_id: int,
        notifications_enabled: bool = True,
        notifications_count: int = 2,
        first_notification_hours: int = 24,
        second_notification_hours: int = 2,
        timezone: str = "Europe/Moscow"
    ) -> NotificationSettings:
        """Создает настройки уведомлений для пользователя."""
        settings = NotificationSettings(
            user_id=user_id,
            notifications_enabled=notifications_enabled,
            notifications_count=notifications_count,
            first_notification_hours=first_notification_hours,
            second_notification_hours=second_notification_hours,
            timezone=timezone
        )
        session.add(settings)
        await session.commit()
        await session.refresh(settings)
        return settings
    
    @staticmethod
    async def get_by_user_id(session: AsyncSession, user_id: int) -> Optional[NotificationSettings]:
        """Получает настройки уведомлений пользователя."""
        result = await session.execute(
            select(NotificationSettings).where(NotificationSettings.user_id == user_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_or_create(session: AsyncSession, user_id: int) -> tuple[NotificationSettings, bool]:
        """Получает настройки или создает дефолтные. Возвращает (settings, created)."""
        settings = await NotificationSettingsCRUD.get_by_user_id(session, user_id)
        if settings:
            return settings, False
        else:
            settings = await NotificationSettingsCRUD.create(session, user_id)
            return settings, True
    
    @staticmethod
    async def update(
        session: AsyncSession,
        user_id: int,
        **kwargs
    ) -> Optional[NotificationSettings]:
        """Обновляет настройки уведомлений пользователя."""
        kwargs['updated_at'] = datetime.now(timezone.utc)
        result = await session.execute(
            update(NotificationSettings)
            .where(NotificationSettings.user_id == user_id)
            .values(**kwargs)
            .returning(NotificationSettings)
        )
        await session.commit()
        return result.scalar_one_or_none()


class DeadlineCRUD:
    """CRUD операции для дедлайнов."""
    
    @staticmethod
    async def create(
        session: AsyncSession,
        subject_id: int,
        title: str,
        hard_deadline: datetime,
        external_id: Optional[str] = None,
        description: Optional[str] = None,
        source_link: Optional[str] = None,
        soft_deadline: Optional[datetime] = None,
        notes: Optional[str] = None
    ) -> Deadline:
        """Создает новый дедлайн."""
        deadline = Deadline(
            external_id=external_id,
            subject_id=subject_id,
            title=title,
            description=description,
            source_link=source_link,
            soft_deadline=soft_deadline,
            hard_deadline=hard_deadline,
            notes=notes
        )
        session.add(deadline)
        await session.commit()
        await session.refresh(deadline)
        return deadline
    
    @staticmethod
    async def get_by_id(session: AsyncSession, deadline_id: int) -> Optional[Deadline]:
        """Получает дедлайн по ID."""
        result = await session.execute(
            select(Deadline).where(Deadline.id == deadline_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_by_external_id(session: AsyncSession, external_id: str) -> Optional[Deadline]:
        """Получает дедлайн по внешнему ID."""
        result = await session.execute(
            select(Deadline).where(Deadline.external_id == external_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_upcoming_deadlines(
        session: AsyncSession,
        hours_ahead: int = 48,
        active_only: bool = True
    ) -> List[Deadline]:
        """Получает предстоящие дедлайны."""
        from_time = datetime.now(timezone.utc)
        to_time = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        to_time = to_time + timezone.timedelta(hours=hours_ahead)
        
        query = select(Deadline).options(joinedload(Deadline.subject)).where(
            and_(
                Deadline.hard_deadline >= from_time,
                Deadline.hard_deadline <= to_time
            )
        )
        if active_only:
            query = query.where(Deadline.is_active == True)
        
        query = query.order_by(asc(Deadline.hard_deadline))
        
        result = await session.execute(query)
        return list(result.scalars().all())
    
    @staticmethod
    async def get_subject_deadlines(
        session: AsyncSession,
        subject_id: int,
        active_only: bool = True
    ) -> List[Deadline]:
        """Получает все дедлайны по дисциплине."""
        query = select(Deadline).where(Deadline.subject_id == subject_id)
        if active_only:
            query = query.where(Deadline.is_active == True)
        
        query = query.order_by(asc(Deadline.hard_deadline))
        
        result = await session.execute(query)
        return list(result.scalars().all())
    
    @staticmethod
    async def upsert_from_sheets(
        session: AsyncSession,
        sheets_data: List[dict]
    ) -> tuple[int, int]:
        """Обновляет дедлайны из Google Sheets. Возвращает (created, updated)."""
        created_count = 0
        updated_count = 0
        
        for row in sheets_data:
            # Парсим данные из Google Sheets
            external_id = str(row.get('ID', ''))
            subject_name = row.get('Дисциплина', '').strip()
            title = row.get('Название ДЗ', '').strip()
            source_link = row.get('Источник \n(Link)', '').strip()
            soft_deadline_str = row.get('Мягкий \nДедлайн', '').strip()
            hard_deadline_str = row.get('Жесткий \nДедлайн', '').strip()
            notes = row.get('Примечание', '').strip()
            
            if not all([subject_name, title, hard_deadline_str]):
                continue  # Пропускаем неполные записи
            
            # Получаем или создаем дисциплину
            subject, _ = await SubjectCRUD.get_or_create(session, subject_name)
            
            # Парсим даты
            try:
                from dateutil import parser
                hard_deadline = parser.parse(hard_deadline_str)
                if hard_deadline.tzinfo is None:
                    hard_deadline = hard_deadline.replace(tzinfo=timezone.utc)
                
                soft_deadline = None
                if soft_deadline_str:
                    soft_deadline = parser.parse(soft_deadline_str)
                    if soft_deadline.tzinfo is None:
                        soft_deadline = soft_deadline.replace(tzinfo=timezone.utc)
            except Exception:
                continue  # Пропускаем записи с некорректными датами
            
            # Проверяем существование дедлайна
            existing_deadline = None
            if external_id:
                existing_deadline = await DeadlineCRUD.get_by_external_id(session, external_id)
            
            if existing_deadline:
                # Обновляем существующий
                await session.execute(
                    update(Deadline)
                    .where(Deadline.id == existing_deadline.id)
                    .values(
                        title=title,
                        source_link=source_link or None,
                        soft_deadline=soft_deadline,
                        hard_deadline=hard_deadline,
                        notes=notes or None,
                        updated_at=datetime.now(timezone.utc)
                    )
                )
                updated_count += 1
            else:
                # Создаем новый
                await DeadlineCRUD.create(
                    session=session,
                    external_id=external_id or None,
                    subject_id=subject.id,
                    title=title,
                    description=None,
                    source_link=source_link or None,
                    soft_deadline=soft_deadline,
                    hard_deadline=hard_deadline,
                    notes=notes or None
                )
                created_count += 1
        
        return created_count, updated_count


class SentNotificationCRUD:
    """CRUD операции для отправленных уведомлений."""
    
    @staticmethod
    async def create(
        session: AsyncSession,
        user_id: int,
        deadline_id: int,
        notification_type: str,
        message_id: Optional[int] = None,
        status: str = "sent"
    ) -> SentNotification:
        """Создает запись об отправленном уведомлении."""
        notification = SentNotification(
            user_id=user_id,
            deadline_id=deadline_id,
            notification_type=notification_type,
            message_id=message_id,
            status=status
        )
        session.add(notification)
        await session.commit()
        await session.refresh(notification)
        return notification
    
    @staticmethod
    async def get_by_user_deadline_type(
        session: AsyncSession,
        user_id: int,
        deadline_id: int,
        notification_type: str
    ) -> Optional[SentNotification]:
        """Получает уведомление по пользователю, дедлайну и типу."""
        result = await session.execute(
            select(SentNotification).where(
                and_(
                    SentNotification.user_id == user_id,
                    SentNotification.deadline_id == deadline_id,
                    SentNotification.notification_type == notification_type
                )
            )
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def update_status(
        session: AsyncSession,
        notification_id: int,
        status: str,
        error_message: Optional[str] = None
    ) -> Optional[SentNotification]:
        """Обновляет статус уведомления."""
        values = {
            'status': status,
            'updated_at': datetime.now(timezone.utc)
        }
        if error_message:
            values['error_message'] = error_message
        if status == 'delivered':
            values['delivered_at'] = datetime.now(timezone.utc)
        
        result = await session.execute(
            update(SentNotification)
            .where(SentNotification.id == notification_id)
            .values(**values)
            .returning(SentNotification)
        )
        await session.commit()
        return result.scalar_one_or_none()
    
    @staticmethod
    async def increment_retry(session: AsyncSession, notification_id: int) -> Optional[SentNotification]:
        """Увеличивает счетчик повторных попыток."""
        result = await session.execute(
            update(SentNotification)
            .where(SentNotification.id == notification_id)
            .values(retry_count=SentNotification.retry_count + 1)
            .returning(SentNotification)
        )
        await session.commit()
        return result.scalar_one_or_none()