"""
Сервис для отправки уведомлений о дедлайнах.
"""
import asyncio
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple
from aiogram import Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.db import (
    get_db_session, UserCRUD, SubscriptionCRUD, DeadlineCRUD,
    NotificationSettingsCRUD, SentNotificationCRUD
)
from src.utils import notifications_logger, settings
from .delivery import DeliveryService, RetryStrategy


class NotificationService:
    """Сервис для отправки уведомлений о дедлайнах."""
    
    def __init__(self, bot: Bot):
        self.bot = bot
        self.logger = notifications_logger
        self.max_retries = settings.notification_retry_attempts
        self.batch_size = settings.notification_batch_size
        self.delivery_service = DeliveryService(bot)
    
    async def check_and_send_notifications(self) -> Dict[str, int]:
        """
        Проверяет дедлайны и отправляет уведомления.
        
        Returns:
            Статистика отправки уведомлений
        """
        stats = {
            'checked_deadlines': 0,
            'notifications_sent': 0,
            'notifications_failed': 0,
            'users_notified': 0,
            'errors': 0
        }
        
        try:
            async with get_db_session() as session:
                # Получаем предстоящие дедлайны (в ближайшие 48 часов)
                upcoming_deadlines = await DeadlineCRUD.get_upcoming_deadlines(
                    session, hours_ahead=48
                )
                
                stats['checked_deadlines'] = len(upcoming_deadlines)
                
                if not upcoming_deadlines:
                    self.logger.info("No upcoming deadlines found")
                    return stats
                
                self.logger.info(f"Found {len(upcoming_deadlines)} upcoming deadlines")
                
                # Обрабатываем каждый дедлайн
                for deadline in upcoming_deadlines:
                    try:
                        deadline_stats = await self._process_deadline_notifications(deadline)
                        
                        stats['notifications_sent'] += deadline_stats['sent']
                        stats['notifications_failed'] += deadline_stats['failed']
                        stats['users_notified'] += deadline_stats['users']
                        
                    except Exception as e:
                        self.logger.error(f"Error processing deadline {deadline.id}: {e}")
                        stats['errors'] += 1
                
                self.logger.info(
                    "Notification check completed",
                    **stats
                )
                
                return stats
                
        except Exception as e:
            self.logger.error(f"Error in notification check: {e}")
            stats['errors'] += 1
            return stats
    
    async def _process_deadline_notifications(self, deadline) -> Dict[str, int]:
        """
        Обрабатывает уведомления для конкретного дедлайна.
        
        Args:
            deadline: Объект дедлайна
            
        Returns:
            Статистика обработки
        """
        stats = {'sent': 0, 'failed': 0, 'users': 0}
        
        try:
            async with get_db_session() as session:
                # Получаем подписчиков дисциплины
                subscriptions = await SubscriptionCRUD.get_subject_subscribers(
                    session, deadline.subject_id
                )
                
                if not subscriptions:
                    return stats
                
                # Группируем пользователей по типам уведомлений
                users_to_notify = await self._get_users_to_notify(session, subscriptions, deadline)
                
                # Отправляем уведомления батчами
                for notification_type, users in users_to_notify.items():
                    if not users:
                        continue
                    
                    batch_stats = await self._send_notifications_batch(
                        users, deadline, notification_type
                    )
                    
                    stats['sent'] += batch_stats['sent']
                    stats['failed'] += batch_stats['failed']
                    stats['users'] += len(users)
                
                return stats
                
        except Exception as e:
            self.logger.error(f"Error processing deadline notifications: {e}")
            return stats
    
    async def _get_users_to_notify(self, session, subscriptions, deadline) -> Dict[str, List]:
        """
        Определяет, каким пользователям нужно отправить уведомления.
        
        Args:
            session: Сессия БД
            subscriptions: Список подписок
            deadline: Дедлайн
            
        Returns:
            Словарь с пользователями для каждого типа уведомления
        """
        users_to_notify = {
            'first': [],
            'second': [],
            'urgent': []
        }
        
        now = datetime.now(timezone.utc)
        time_until_deadline = deadline.hard_deadline - now
        hours_until = time_until_deadline.total_seconds() / 3600
        
        for subscription in subscriptions:
            try:
                user = subscription.user
                
                # Получаем настройки уведомлений пользователя
                settings_obj, _ = await NotificationSettingsCRUD.get_or_create(
                    session, user.id
                )
                
                if not settings_obj.notifications_enabled:
                    continue
                
                # Определяем, какие уведомления нужно отправить
                notification_types = self._determine_notification_types(
                    settings_obj, hours_until
                )
                
                for notification_type in notification_types:
                    # Проверяем, не отправляли ли уже это уведомление
                    existing_notification = await SentNotificationCRUD.get_by_user_deadline_type(
                        session, user.id, deadline.id, notification_type
                    )
                    
                    if not existing_notification:
                        users_to_notify[notification_type].append({
                            'user': user,
                            'settings': settings_obj,
                            'subscription': subscription
                        })
                
            except Exception as e:
                self.logger.error(f"Error processing user {subscription.user_id}: {e}")
        
        return users_to_notify
    
    def _determine_notification_types(self, settings_obj, hours_until: float) -> List[str]:
        """
        Определяет типы уведомлений для отправки.
        
        Args:
            settings_obj: Настройки уведомлений пользователя
            hours_until: Часов до дедлайна
            
        Returns:
            Список типов уведомлений
        """
        notification_types = []
        
        # Проверяем первое уведомление
        if (settings_obj.notifications_count >= 1 and 
            hours_until <= settings_obj.first_notification_hours and 
            hours_until > settings_obj.second_notification_hours):
            notification_types.append('first')
        
        # Проверяем второе уведомление
        if (settings_obj.notifications_count >= 2 and 
            hours_until <= settings_obj.second_notification_hours and 
            hours_until > 0):
            notification_types.append('second')
        
        # Проверяем срочное уведомление (менее часа до дедлайна)
        if hours_until <= 1 and hours_until > 0:
            notification_types.append('urgent')
        
        return notification_types
    
    async def _send_notifications_batch(
        self, 
        users: List[Dict], 
        deadline, 
        notification_type: str
    ) -> Dict[str, int]:
        """
        Отправляет уведомления батчем.
        
        Args:
            users: Список пользователей для уведомления
            deadline: Дедлайн
            notification_type: Тип уведомления
            
        Returns:
            Статистика отправки
        """
        stats = {'sent': 0, 'failed': 0}
        
        # Разбиваем на батчи
        for i in range(0, len(users), self.batch_size):
            batch = users[i:i + self.batch_size]
            
            # Отправляем уведомления в батче
            tasks = []
            for user_data in batch:
                task = self._send_single_notification(
                    user_data, deadline, notification_type
                )
                tasks.append(task)
            
            # Ждем завершения всех задач в батче
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Подсчитываем статистику
            for result in results:
                if isinstance(result, Exception):
                    stats['failed'] += 1
                elif result:
                    stats['sent'] += 1
                else:
                    stats['failed'] += 1
            
            # Пауза между батчами для соблюдения rate limits
            if i + self.batch_size < len(users):
                await asyncio.sleep(1)
        
        return stats
    
    async def _send_single_notification(
        self, 
        user_data: Dict, 
        deadline, 
        notification_type: str
    ) -> bool:
        """
        Отправляет одно уведомление пользователю.
        
        Args:
            user_data: Данные пользователя
            deadline: Дедлайн
            notification_type: Тип уведомления
            
        Returns:
            True, если уведомление отправлено успешно
        """
        user = user_data['user']
        settings_obj = user_data['settings']
        
        try:
            # Создаем запись об уведомлении в БД
            async with get_db_session() as session:
                notification_record = await SentNotificationCRUD.create(
                    session=session,
                    user_id=user.id,
                    deadline_id=deadline.id,
                    notification_type=notification_type,
                    status='pending'
                )
            
            # Формируем текст уведомления
            message_text = self._format_notification_message(
                deadline, notification_type, settings_obj
            )
            
            # Создаем клавиатуру
            keyboard = self._create_notification_keyboard(deadline)
            
            # Отправляем сообщение через сервис надежной доставки
            success, message_id, error = await self.delivery_service.send_message_with_retry(
                chat_id=user.telegram_id,
                text=message_text,
                reply_markup=keyboard.as_markup() if keyboard else None,
                parse_mode='HTML',
                notification_id=notification_record.id,
                retry_strategy=RetryStrategy.EXPONENTIAL_BACKOFF
            )
            
            if success:
                self.logger.notification_sent(
                    user_id=user.telegram_id,
                    deadline_id=deadline.id,
                    notification_type=notification_type,
                    status='sent',
                    message_id=message_id
                )
            else:
                self.logger.notification_failed(
                    user_id=user.telegram_id,
                    deadline_id=deadline.id,
                    error=error or "Unknown error"
                )
            
            return success
            
        except Exception as e:
            # Другие ошибки
            self.logger.notification_failed(
                user_id=user.telegram_id,
                deadline_id=deadline.id,
                error=str(e)
            )
            return False
    
    def _format_notification_message(
        self, 
        deadline, 
        notification_type: str, 
        settings_obj
    ) -> str:
        """
        Форматирует текст уведомления.
        
        Args:
            deadline: Дедлайн
            notification_type: Тип уведомления
            settings_obj: Настройки пользователя
            
        Returns:
            Отформатированный текст сообщения
        """
        # Вычисляем время до дедлайна
        now = datetime.now(timezone.utc)
        time_until = deadline.hard_deadline - now
        
        # Форматируем время
        if time_until.days > 0:
            time_str = f"{time_until.days} дн. {time_until.seconds // 3600} ч."
        elif time_until.seconds > 3600:
            time_str = f"{time_until.seconds // 3600} ч. {(time_until.seconds % 3600) // 60} мин."
        else:
            time_str = f"{time_until.seconds // 60} мин."
        
        # Выбираем эмодзи и заголовок в зависимости от типа уведомления
        if notification_type == 'urgent':
            emoji = "🚨"
            title = "СРОЧНО! Дедлайн через час!"
        elif notification_type == 'second':
            emoji = "⏰"
            title = "Напоминание о дедлайне"
        else:
            emoji = "📅"
            title = "Приближается дедлайн"
        
        # Форматируем дату дедлайна в московском времени
        import pytz
        moscow_tz = pytz.timezone('Europe/Moscow')
        deadline_moscow = deadline.hard_deadline.astimezone(moscow_tz)
        deadline_str = deadline_moscow.strftime("%d.%m.%Y в %H:%M")
        
        # Формируем основной текст
        message_text = (
            f"{emoji} <b>{title}</b>\n\n"
            f"📚 <b>Дисциплина:</b> {deadline.subject.name}\n"
            f"📝 <b>Задание:</b> {deadline.title}\n"
            f"⏳ <b>Осталось:</b> {time_str}\n"
            f"📅 <b>Дедлайн:</b> {deadline_str} (МСК)\n"
        )
        
        # Добавляем ссылку на источник, если есть
        if deadline.source_link:
            message_text += f"🔗 <b>Ссылка:</b> {deadline.source_link}\n"
        
        # Добавляем примечания, если есть
        if deadline.notes:
            message_text += f"📋 <b>Примечание:</b> {deadline.notes}\n"
        
        # Добавляем мотивационное сообщение
        if notification_type == 'urgent':
            message_text += "\n💪 Последний рывок! Вы справитесь!"
        elif notification_type == 'second':
            message_text += "\n⚡ Время поторопиться!"
        else:
            message_text += "\n🎯 Не забудьте выполнить задание вовремя!"
        
        return message_text
    
    def _create_notification_keyboard(self, deadline) -> Optional[InlineKeyboardBuilder]:
        """
        Создает клавиатуру для уведомления.
        
        Args:
            deadline: Дедлайн
            
        Returns:
            Клавиатура или None
        """
        keyboard = InlineKeyboardBuilder()
        
        # Кнопка для перехода к источнику
        if deadline.source_link:
            keyboard.button(text="🔗 Открыть задание", url=deadline.source_link)
        
        # Кнопка для управления подписками
        keyboard.button(text="⚙️ Настройки", callback_data="settings")
        
        if keyboard._buttons:
            keyboard.adjust(1)
            return keyboard
        
        return None
    
    async def _handle_blocked_user(self, user):
        """
        Обрабатывает случай, когда пользователь заблокировал бота.
        
        Args:
            user: Пользователь
        """
        try:
            async with get_db_session() as session:
                await UserCRUD.set_blocked(session, user.telegram_id, True)
            
            self.logger.user_action(
                user_id=user.telegram_id,
                action="user_blocked_bot",
                username=user.username
            )
            
        except Exception as e:
            self.logger.error(f"Error handling blocked user: {e}")
    
    async def send_test_notification(self, user_telegram_id: int, deadline_id: int) -> bool:
        """
        Отправляет тестовое уведомление пользователю.
        
        Args:
            user_telegram_id: Telegram ID пользователя
            deadline_id: ID дедлайна
            
        Returns:
            True, если уведомление отправлено успешно
        """
        try:
            async with get_db_session() as session:
                # Получаем пользователя
                user = await UserCRUD.get_by_telegram_id(session, user_telegram_id)
                if not user:
                    return False
                
                # Получаем дедлайн
                deadline = await DeadlineCRUD.get_by_id(session, deadline_id)
                if not deadline:
                    return False
                
                # Получаем настройки
                settings_obj, _ = await NotificationSettingsCRUD.get_or_create(
                    session, user.id
                )
                
                # Формируем данные пользователя
                user_data = {
                    'user': user,
                    'settings': settings_obj
                }
                
                # Отправляем тестовое уведомление
                return await self._send_single_notification(
                    user_data, deadline, 'test'
                )
                
        except Exception as e:
            self.logger.error(f"Error sending test notification: {e}")
            return False