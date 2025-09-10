from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import pytz
from sqlalchemy import select, and_

from src.core.database import db_manager
from src.core.models import User, Deadline, Subject, Subscription, UserNotificationSettings, ScheduledNotification
from src.utils import get_logger

logger = get_logger()

class NotificationSchedulerService:
    """Сервис для планирования уведомлений о дедлайнах"""
    
    def __init__(self):
        self.moscow_tz = pytz.timezone('Europe/Moscow')
    
    async def schedule_notifications_for_deadline(self, deadline: Deadline) -> int:
        """Создать запланированные уведомления для дедлайна"""
        try:
            # Получаем всех пользователей, подписанных на предмет этого дедлайна
            subscribed_users = await self._get_subscribed_users(deadline.subject_id)
            
            if not subscribed_users:
                logger.info(f"Нет подписчиков на предмет дедлайна {deadline.id}")
                return 0
            
            total_scheduled = 0
            
            for user in subscribed_users:
                # Получаем настройки уведомлений пользователя
                settings = await db_manager.get_user_notification_settings(user.tg_user_id)
                
                if not settings.is_active:
                    continue
                
                # Планируем уведомления для soft deadline
                if deadline.soft_deadline_ts:
                    soft_count = await self._schedule_notifications_for_user_deadline(
                        user, deadline, 'soft', deadline.soft_deadline_ts, settings
                    )
                    total_scheduled += soft_count
                
                # Планируем уведомления для hard deadline
                if deadline.hard_deadline_ts:
                    hard_count = await self._schedule_notifications_for_user_deadline(
                        user, deadline, 'hard', deadline.hard_deadline_ts, settings
                    )
                    total_scheduled += hard_count
            
            logger.info(f"Запланировано {total_scheduled} уведомлений для дедлайна {deadline.id}")
            return total_scheduled
            
        except Exception as e:
            logger.error(f"Ошибка планирования уведомлений для дедлайна {deadline.id}: {e}")
            return 0
    
    async def _get_subscribed_users(self, subject_id: int) -> List[User]:
        """Получить пользователей, подписанных на предмет"""
        async with db_manager.async_session() as session:
            try:
                stmt = select(User).join(Subscription).where(
                    Subscription.subject_id == subject_id
                )
                result = await session.execute(stmt)
                return list(result.scalars().all())
                
            except Exception as e:
                logger.error(f"Ошибка получения подписчиков предмета {subject_id}: {e}")
                return []
    
    async def _schedule_notifications_for_user_deadline(
        self, user: User, deadline: Deadline, deadline_type: str, 
        deadline_ts: datetime, settings: UserNotificationSettings
    ) -> int:
        """Создать уведомления для пользователя и конкретного дедлайна"""
        try:
            scheduled_count = 0
            
            # Планируем первое напоминание
            reminder1_time = self._calculate_notification_time(
                deadline_ts, settings.reminder1_offset, settings.reminder1_unit
            )
            
            if reminder1_time and reminder1_time > datetime.now(self.moscow_tz):
                await self._create_scheduled_notification(
                    user.tg_user_id, deadline.id, deadline_type, 1,
                    deadline_ts, reminder1_time
                )
                scheduled_count += 1
            
            # Планируем второе напоминание
            reminder2_time = self._calculate_notification_time(
                deadline_ts, settings.reminder2_offset, settings.reminder2_unit
            )
            
            if reminder2_time and reminder2_time > datetime.now(self.moscow_tz):
                await self._create_scheduled_notification(
                    user.tg_user_id, deadline.id, deadline_type, 2,
                    deadline_ts, reminder2_time
                )
                scheduled_count += 1
            
            return scheduled_count
            
        except Exception as e:
            logger.error(f"Ошибка планирования уведомлений для пользователя {user.tg_user_id}: {e}")
            return 0
    
    def _calculate_notification_time(self, deadline_ts: datetime, offset: int, unit: str) -> Optional[datetime]:
        """Вычислить время отправки уведомления"""
        try:
            if unit == 'days':
                delta = timedelta(days=offset)
            elif unit == 'hours':
                delta = timedelta(hours=offset)
            else:
                logger.warning(f"Неизвестная единица времени: {unit}")
                return None
            
            notification_time = deadline_ts - delta
            
            # Проверяем, что время уведомления не в прошлом
            if notification_time <= datetime.now(self.moscow_tz):
                return None
            
            return notification_time
            
        except Exception as e:
            logger.error(f"Ошибка вычисления времени уведомления: {e}")
            return None
    
    async def _create_scheduled_notification(
        self, user_id: int, deadline_id: int, deadline_type: str,
        notification_number: int, original_deadline_ts: datetime,
        planned_delivery_time: datetime
    ) -> bool:
        """Создать запись запланированного уведомления"""
        try:
            # Проверяем, не существует ли уже такое уведомление
            async with db_manager.async_session() as session:
                existing_stmt = select(ScheduledNotification).where(
                    and_(
                        ScheduledNotification.user_id == user_id,
                        ScheduledNotification.deadline_id == deadline_id,
                        ScheduledNotification.deadline_type == deadline_type,
                        ScheduledNotification.notification_number == notification_number
                    )
                )
                result = await session.execute(existing_stmt)
                existing = result.scalar_one_or_none()
                
                if existing:
                    # Обновляем существующее уведомление
                    existing.original_deadline_ts = original_deadline_ts
                    existing.planned_delivery_time = planned_delivery_time
                    existing.status = 'scheduled'
                    existing.updated_at = datetime.now(self.moscow_tz)
                    await session.commit()
                    return True
            
            # Создаем новое уведомление
            notification_data = {
                'user_id': user_id,
                'deadline_id': deadline_id,
                'deadline_type': deadline_type,
                'notification_number': notification_number,
                'original_deadline_ts': original_deadline_ts,
                'planned_delivery_time': planned_delivery_time,
                'status': 'scheduled'
            }
            
            await db_manager.create_scheduled_notification(notification_data)
            return True
            
        except Exception as e:
            logger.error(f"Ошибка создания запланированного уведомления: {e}")
            return False
    
    async def reschedule_notifications_for_updated_deadline(self, deadline: Deadline) -> int:
        """Перепланировать уведомления для обновленного дедлайна"""
        try:
            # Отменяем существующие запланированные уведомления
            cancelled_count = await db_manager.cancel_scheduled_notifications_for_deadline(deadline.id)
            logger.info(f"Отменено {cancelled_count} уведомлений для обновленного дедлайна {deadline.id}")
            
            # Создаем новые уведомления
            scheduled_count = await self.schedule_notifications_for_deadline(deadline)
            
            return scheduled_count
            
        except Exception as e:
            logger.error(f"Ошибка перепланирования уведомлений для дедлайна {deadline.id}: {e}")
            return 0
    
    async def reschedule_notifications_for_user_settings_change(self, user_id: int) -> int:
        """Перепланировать все уведомления пользователя при изменении настроек"""
        try:
            # Получаем все активные дедлайны пользователя
            async with db_manager.async_session() as session:
                stmt = select(Deadline).join(Subject).join(Subscription).where(
                    and_(
                        Subscription.user_id == user_id,
                        Subject.is_active == True
                    )
                )
                result = await session.execute(stmt)
                user_deadlines = result.scalars().all()
            
            total_rescheduled = 0
            
            for deadline in user_deadlines:
                # Отменяем существующие уведомления пользователя для этого дедлайна
                async with db_manager.async_session() as session:
                    cancel_stmt = select(ScheduledNotification).where(
                        and_(
                            ScheduledNotification.user_id == user_id,
                            ScheduledNotification.deadline_id == deadline.id,
                            ScheduledNotification.status == 'scheduled'
                        )
                    )
                    result = await session.execute(cancel_stmt)
                    notifications_to_cancel = result.scalars().all()
                    
                    for notification in notifications_to_cancel:
                        notification.status = 'cancelled'
                        notification.updated_at = datetime.now(self.moscow_tz)
                    
                    await session.commit()
                
                # Создаем новые уведомления для этого пользователя и дедлайна
                user = await db_manager.get_user_by_id(user_id)
                if not user:
                    continue  # Пользователь не найден, пропускаем
                    
                settings = await db_manager.get_user_notification_settings(user_id)
                
                if settings.is_active:
                    # Планируем для soft deadline
                    if deadline.soft_deadline_ts:
                        count = await self._schedule_notifications_for_user_deadline(
                            user, deadline, 'soft', deadline.soft_deadline_ts, settings
                        )
                        total_rescheduled += count
                    
                    # Планируем для hard deadline
                    if deadline.hard_deadline_ts:
                        count = await self._schedule_notifications_for_user_deadline(
                            user, deadline, 'hard', deadline.hard_deadline_ts, settings
                        )
                        total_rescheduled += count
            
            logger.info(f"Перепланировано {total_rescheduled} уведомлений для пользователя {user_id}")
            return total_rescheduled
            
        except Exception as e:
            logger.error(f"Ошибка перепланирования уведомлений для пользователя {user_id}: {e}")
            return 0

# Создаем экземпляр сервиса
notification_scheduler_service = NotificationSchedulerService()
