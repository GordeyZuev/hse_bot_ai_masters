from typing import List, Dict, Any
from datetime import datetime, timedelta
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
import pytz

from src.core.database import db_manager
from src.core.models import User, Deadline, Subject, Subscription, UserNotification, NotificationLog
from src.bot.services.notification_service import notification_service
from src.utils import get_logger
from sqlalchemy import select, and_, or_

logger = get_logger()

class NotificationSender:
    """Сервис для отправки уведомлений о дедлайнах"""
    
    def __init__(self):
        self.moscow_tz = pytz.timezone('Europe/Moscow')
    
    async def send_deadline_notifications(self, bot: Bot) -> Dict[str, int]:
        """Отправить уведомления о приближающихся дедлайнах"""
        try:
            logger.info("Начинаю отправку уведомлений о дедлайнах")
            
            # Получаем всех пользователей с активными настройками уведомлений
            users_to_notify = await self._get_users_for_notifications()
            
            if not users_to_notify:
                logger.info("Нет пользователей для уведомлений")
                return {'sent': 0, 'errors': 0, 'skipped': 0}
            
            sent_count = 0
            error_count = 0
            skipped_count = 0
            
            for user_data in users_to_notify:
                try:
                    user = user_data['user']
                    notifications_settings = user_data['notifications']
                    
                    # Получаем дедлайны для каждой настройки уведомлений
                    for notification_setting in notifications_settings:
                        if not notification_setting.is_enabled:
                            continue
                        
                        # Вычисляем временной диапазон для уведомления
                        notification_time = self._calculate_notification_time(notification_setting)
                        
                        # Получаем дедлайны пользователя в этом диапазоне
                        deadlines_to_notify = await self._get_user_deadlines_for_notification(
                            user.tg_user_id, notification_time
                        )
                        
                        if not deadlines_to_notify:
                            continue
                        
                        # Проверяем, не отправляли ли уже уведомления об этих дедлайнах
                        filtered_deadlines = await self._filter_already_notified_deadlines(
                            user.tg_user_id, deadlines_to_notify, notification_setting.notification_number
                        )
                        
                        if not filtered_deadlines:
                            skipped_count += 1
                            continue
                        
                        # Отправляем уведомление
                        success = await self._send_notification_to_user(
                            bot, user, filtered_deadlines, notification_setting
                        )
                        
                        if success:
                            sent_count += 1
                            # Записываем в лог отправленные уведомления
                            await self._log_sent_notifications(
                                user.tg_user_id, filtered_deadlines, notification_setting.notification_number
                            )
                        else:
                            error_count += 1
                
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления пользователю {user_data['user'].tg_user_id}: {e}")
                    error_count += 1
            
            logger.info(f"Уведомления отправлены: {sent_count} успешно, {error_count} ошибок, {skipped_count} пропущено")
            
            return {
                'sent': sent_count,
                'errors': error_count,
                'skipped': skipped_count
            }
            
        except Exception as e:
            logger.error(f"Ошибка отправки уведомлений: {e}")
            return {'sent': 0, 'errors': 0, 'skipped': 0}
    
    async def _get_users_for_notifications(self) -> List[Dict[str, Any]]:
        """Получить пользователей с активными настройками уведомлений"""
        async with db_manager.async_session() as session:
            try:
                
                # Получаем пользователей с активными уведомлениями и подписками
                stmt = select(User).join(UserNotification).join(Subscription).where(
                    UserNotification.is_enabled == True
                ).distinct()
                
                result = await session.execute(stmt)
                users = result.scalars().all()
                
                users_data = []
                for user in users:
                    # Получаем настройки уведомлений для каждого пользователя
                    notifications = await notification_service.get_user_notifications(user.tg_user_id)
                    if notifications:
                        users_data.append({
                            'user': user,
                            'notifications': notifications
                        })
                
                return users_data
                
            except Exception as e:
                logger.error(f"Ошибка получения пользователей для уведомлений: {e}")
                return []
    
    def _calculate_notification_time(self, notification_setting: UserNotification) -> Dict[str, datetime]:
        """Вычислить временной диапазон для уведомления"""
        now = datetime.now(self.moscow_tz)
        
        # Конвертируем offset в часы
        if notification_setting.offset_unit == 'days':
            hours_offset = notification_setting.offset_value * 24
        elif notification_setting.offset_unit == 'hours':
            hours_offset = notification_setting.offset_value
        elif notification_setting.offset_unit == 'minutes':
            hours_offset = notification_setting.offset_value / 60
        else:
            hours_offset = 24  # По умолчанию 24 часа
        
        # Временной диапазон: от (offset - 1 час) до (offset + 1 час)
        # Это позволяет отправлять уведомления в нужное время с небольшим допуском
        start_time = now + timedelta(hours=hours_offset - 1)
        end_time = now + timedelta(hours=hours_offset + 1)
        
        return {
            'start': start_time,
            'end': end_time,
            'offset_hours': hours_offset
        }
    
    async def _get_user_deadlines_for_notification(
        self, user_id: int, notification_time: Dict[str, datetime]
    ) -> List[Dict[str, Any]]:
        """Получить дедлайны пользователя для уведомления"""
        async with db_manager.async_session() as session:
            try:

                
                # Получаем подписки пользователя
                subscriptions_stmt = select(Subscription.subject_id).where(
                    Subscription.user_id == user_id
                )
                subscriptions_result = await session.execute(subscriptions_stmt)
                subscribed_subject_ids = [row[0] for row in subscriptions_result.fetchall()]
                
                if not subscribed_subject_ids:
                    return []
                
                start_time = notification_time['start']
                end_time = notification_time['end']
                
                # Получаем дедлайны в нужном временном диапазоне
                stmt = select(Deadline, Subject).join(Subject).where(
                    and_(
                        Deadline.subject_id.in_(subscribed_subject_ids),
                        or_(
                            and_(
                                Deadline.soft_deadline_ts.isnot(None),
                                Deadline.soft_deadline_ts >= start_time,
                                Deadline.soft_deadline_ts <= end_time
                            ),
                            and_(
                                Deadline.hard_deadline_ts.isnot(None),
                                Deadline.hard_deadline_ts >= start_time,
                                Deadline.hard_deadline_ts <= end_time
                            )
                        )
                    )
                )
                
                result = await session.execute(stmt)
                deadlines_data = []
                
                for deadline, subject in result.fetchall():
                    deadlines_data.append({
                        'deadline': deadline,
                        'subject': subject
                    })
                
                return deadlines_data
                
            except Exception as e:
                logger.error(f"Ошибка получения дедлайнов для уведомления пользователя {user_id}: {e}")
                return []
    
    async def _filter_already_notified_deadlines(
        self, user_id: int, deadlines_data: List[Dict[str, Any]], notification_number: int
    ) -> List[Dict[str, Any]]:
        """Фильтровать дедлайны, о которых уже отправлялись уведомления"""
        async with db_manager.async_session() as session:
            try:
                
                # Получаем уже отправленные уведомления
                deadline_ids = [data['deadline'].id for data in deadlines_data]
                
                stmt = select(NotificationLog.deadline_id).where(
                    NotificationLog.user_id == user_id,
                    NotificationLog.deadline_id.in_(deadline_ids),
                    NotificationLog.notification_type == f"notification_{notification_number}",
                    NotificationLog.status == 'sent'
                )
                
                result = await session.execute(stmt)
                notified_deadline_ids = set(row[0] for row in result.fetchall())
                
                # Фильтруем дедлайны
                filtered_deadlines = [
                    data for data in deadlines_data
                    if data['deadline'].id not in notified_deadline_ids
                ]
                
                return filtered_deadlines
                
            except Exception as e:
                logger.error(f"Ошибка фильтрации уведомлений: {e}")
                return deadlines_data  # В случае ошибки возвращаем все
    
    async def _send_notification_to_user(
        self, bot: Bot, user: User, deadlines_data: List[Dict[str, Any]], notification_setting: UserNotification
    ) -> bool:
        """Отправить уведомление пользователю"""
        try:
            if len(deadlines_data) == 1:
                # Одиночное уведомление
                data = deadlines_data[0]
                message_text = self._format_single_deadline_notification(data, notification_setting)
            else:
                # Групповое уведомление
                message_text = self._format_multiple_deadlines_notification(deadlines_data, notification_setting)
            
            await bot.send_message(
                chat_id=user.tg_user_id,
                text=message_text,
                parse_mode='HTML',
                disable_web_page_preview=True
            )
            
            logger.info(f"Уведомление отправлено пользователю {user.tg_user_id}")
            return True
            
        except TelegramForbiddenError:
            logger.warning(f"Пользователь {user.tg_user_id} заблокировал бота")
            return False
        except TelegramBadRequest as e:
            logger.warning(f"Ошибка отправки пользователю {user.tg_user_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Неожиданная ошибка отправки пользователю {user.tg_user_id}: {e}")
            return False
    
    def _format_single_deadline_notification(
        self, deadline_data: Dict[str, Any], notification_setting: UserNotification
    ) -> str:
        """Форматировать уведомление об одном дедлайне"""
        deadline = deadline_data['deadline']
        subject = deadline_data['subject']
        
        # Определяем единицу времени для сообщения
        unit_text = {
            'days': 'дн.',
            'hours': 'ч.',
            'minutes': 'мин.'
        }.get(notification_setting.offset_unit, notification_setting.offset_unit)
        
        message = f"🔔 <b>Напоминание о дедлайне</b>\n\n"
        message += f"📚 <b>{subject.name}</b>\n"
        message += f"📝 <b>{deadline.hw_name}</b>\n\n"
        
        # Информация о дедлайнах
        if deadline.soft_deadline_ts:
            soft_date = deadline.soft_deadline_ts.strftime("%d.%m.%Y %H:%M")
            message += f"🟡 <b>Мягкий дедлайн:</b> {soft_date}\n"
        
        if deadline.hard_deadline_ts:
            hard_date = deadline.hard_deadline_ts.strftime("%d.%m.%Y %H:%M")
            message += f"🔴 <b>Жесткий дедлайн:</b> {hard_date}\n"
        
        message += f"\n⏰ <b>Осталось:</b> {notification_setting.offset_value} {unit_text}"
        
        if deadline.source_link:
            message += f"\n\n🔗 <a href='{deadline.source_link}'>Перейти к заданию</a>"
        
        if deadline.note:
            message += f"\n\n💬 <i>{deadline.note}</i>"
        
        return message
    
    def _format_multiple_deadlines_notification(
        self, deadlines_data: List[Dict[str, Any]], notification_setting: UserNotification
    ) -> str:
        """Форматировать уведомление о нескольких дедлайнах"""
        unit_text = {
            'days': 'дн.',
            'hours': 'ч.',
            'minutes': 'мин.'
        }.get(notification_setting.offset_unit, notification_setting.offset_unit)
        
        message = f"🔔 <b>Напоминание о дедлайнах</b>\n\n"
        message += f"У вас {len(deadlines_data)} дедлайнов через {notification_setting.offset_value} {unit_text}:\n\n"
        
        for i, data in enumerate(deadlines_data, 1):
            deadline = data['deadline']
            subject = data['subject']
            
            message += f"<b>{i}. {subject.name}</b>\n"
            message += f"📝 {deadline.hw_name}\n"
            
            if deadline.soft_deadline_ts:
                date_str = deadline.soft_deadline_ts.strftime("%d.%m %H:%M")
                message += f"🟡 {date_str}\n"
            elif deadline.hard_deadline_ts:
                date_str = deadline.hard_deadline_ts.strftime("%d.%m %H:%M")
                message += f"🔴 {date_str}\n"
            
            message += "\n"
        
        message += "Используйте /deadlines для подробной информации."
        
        return message
    
    async def _log_sent_notifications(
        self, user_id: int, deadlines_data: List[Dict[str, Any]], notification_number: int
    ):
        """Записать отправленные уведомления в лог"""
        async with db_manager.async_session() as session:
            try:
                current_time = datetime.now(self.moscow_tz)
                
                for data in deadlines_data:
                    deadline = data['deadline']
                    
                    log_entry = NotificationLog(
                        user_id=user_id,
                        deadline_id=deadline.id,
                        notification_type=f"notification_{notification_number}",
                        scheduled_for=current_time,
                        status='sent',
                        attempt_count=1,
                        sent_at=current_time
                    )
                    session.add(log_entry)
                
                await session.commit()
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка записи лога уведомлений: {e}")

# Создаем экземпляр сервиса
notification_sender = NotificationSender()