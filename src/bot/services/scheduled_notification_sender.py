import asyncio
from typing import List, Dict, Any
from datetime import datetime, timedelta, timezone
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
import pytz

from src.core.database import db_manager
from src.core.models import User, Deadline, Subject, ScheduledNotification
from src.utils import get_logger
from sqlalchemy import select

logger = get_logger()

class ScheduledNotificationSender:
    """Сервис для отправки предрассчитанных уведомлений о дедлайнах"""
    
    def __init__(self):
        pass
    
    async def send_scheduled_notifications(self, bot: Bot) -> Dict[str, int]:
        """Отправить все запланированные уведомления"""
        stats = {
            'sent': 0,
            'failed': 0,
            'skipped': 0,
            'total_processed': 0
        }
        
        try:
            logger.info("Начинаем отправку запланированных уведомлений")
            
            # Получаем уведомления для отправки (в течение ближайших 5 минут)
            notifications = await db_manager.get_scheduled_notifications_for_delivery(time_window_minutes=5)
            
            if not notifications:
                logger.info("Нет уведомлений для отправки")
                return stats
            
            logger.info(f"Найдено {len(notifications)} уведомлений для отправки")
            
            # Группируем уведомления по пользователям
            user_notifications = self._group_notifications_by_user(notifications)
            
            # Обрабатываем пользователей батчами для лучшей производительности
            batch_size = 10
            user_items = list(user_notifications.items())
            
            for i in range(0, len(user_items), batch_size):
                batch = user_items[i:i + batch_size]
                
                # Обрабатываем батч параллельно
                tasks = []
                for user_id, user_notifs in batch:
                    task = self._process_user_notifications(bot, user_id, user_notifs, stats)
                    tasks.append(task)
                
                # Ждем завершения всех задач в батче
                await asyncio.gather(*tasks, return_exceptions=True)
            
            logger.info(f"Отправка завершена. Статистика: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"Критическая ошибка при отправке уведомлений: {e}")
            return stats
    
    def _group_notifications_by_user(self, notifications: List[ScheduledNotification]) -> Dict[int, List[ScheduledNotification]]:
        """Группировать уведомления по пользователям"""
        user_notifications = {}
        
        for notification in notifications:
            user_id = notification.user_id
            if user_id not in user_notifications:
                user_notifications[user_id] = []
            user_notifications[user_id].append(notification)
        
        return user_notifications
    
    async def _process_user_notifications(self, bot: Bot, user_id: int, user_notifs: List[ScheduledNotification], stats: Dict[str, int]):
        """Обработать уведомления для одного пользователя"""
        try:
            success = await self._send_notifications_to_user(bot, user_id, user_notifs)
            
            if success:
                stats['sent'] += len(user_notifs)
                # Обновляем статус уведомлений на 'sent'
                for notification in user_notifs:
                    await db_manager.update_notification_status(notification.id, 'sent')
            else:
                stats['failed'] += len(user_notifs)
                # Обновляем статус уведомлений на 'failed'
                for notification in user_notifs:
                    await db_manager.update_notification_status(notification.id, 'failed')
            
            stats['total_processed'] += len(user_notifs)
            
        except Exception as e:
            logger.error(f"Ошибка отправки уведомлений пользователю {user_id}: {e}")
            stats['failed'] += len(user_notifs)
            stats['total_processed'] += len(user_notifs)
            
            # Отмечаем уведомления как неудачные
            for notification in user_notifs:
                await db_manager.update_notification_status(notification.id, 'failed')
    
    async def _send_notifications_to_user(self, bot: Bot, user_id: int, notifications: List[ScheduledNotification]) -> bool:
        """Отправить уведомления конкретному пользователю"""
        try:
            # Загружаем полную информацию о дедлайнах одним запросом
            notification_data = []
            
            # Собираем все ID дедлайнов для одного запроса
            deadline_ids = [notification.deadline_id for notification in notifications]
            
            async with db_manager.async_session() as session:
                stmt = select(Deadline, Subject).join(Subject).where(
                    Deadline.id.in_(deadline_ids)
                )
                result = await session.execute(stmt)
                deadline_subjects = result.all()
                
                # Создаем словарь для быстрого поиска
                deadline_dict = {deadline.id: (deadline, subject) for deadline, subject in deadline_subjects}
                
                for notification in notifications:
                    if notification.deadline_id in deadline_dict:
                        deadline, subject = deadline_dict[notification.deadline_id]
                        notification_data.append({
                            'notification': notification,
                            'deadline': deadline,
                            'subject': subject
                        })
            
            if not notification_data:
                logger.warning(f"Не найдены дедлайны для уведомлений пользователя {user_id}")
                return False
            
            # Определяем TZ пользователя для форматирования
            user = await db_manager.get_user_by_id(user_id)
            user_tz = pytz.timezone(user.timezone) if user and user.timezone else pytz.UTC
            
            message = await self._format_notifications_message(notification_data, user_tz)
            
            # Проверяем задержку по UTC
            now_utc = datetime.now(timezone.utc)
            planned_times = [d['notification'].planned_delivery_time for d in notification_data]
            delay_threshold = now_utc - timedelta(minutes=30)
            is_delayed = any(pt and pt < delay_threshold for pt in planned_times)
            
            if is_delayed:
                message = "⚠️ <i>Отправлено с задержкой (>30 мин)</i>\n\n" + message
            
            # Клавиатура для быстрого перехода к дедлайнам
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📅 Дедлайны", callback_data="quick_deadlines")]
            ])
            
            # Отправляем сообщение
            await bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode='HTML',
                disable_web_page_preview=True,
                reply_markup=keyboard
            )
            
            logger.info(f"Отправлено {len(notifications)} уведомлений пользователю {user_id}")
            return True
            
        except TelegramForbiddenError:
            logger.warning(f"Пользователь {user_id} заблокировал бота")
            return False
            
        except TelegramBadRequest as e:
            logger.error(f"Ошибка Telegram API для пользователя {user_id}: {e}")
            return False
            
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления пользователю {user_id}: {e}")
            return False
    
    async def _format_notifications_message(self, notification_data: List[Dict[str, Any]], user_tz) -> str:
        """Форматировать сообщение с уведомлениями"""
        if len(notification_data) == 1:
            return self._format_single_notification(notification_data[0], user_tz)
        else:
            return self._format_multiple_notifications(notification_data, user_tz)
    
    def _format_single_notification(self, data: Dict[str, Any], user_tz) -> str:
        """Форматировать одиночное уведомление"""
        notification = data['notification']
        deadline = data['deadline']
        subject = data['subject']
        
        deadline_type_icon = "🟡" if notification.deadline_type == 'soft' else "🔴"
        
        # Определяем какой дедлайн использовать
        if notification.deadline_type == 'soft':
            deadline_ts = deadline.soft_deadline_ts
        else:
            deadline_ts = deadline.hard_deadline_ts
        
        # Форматируем дату в TZ пользователя
        local_deadline = deadline_ts.astimezone(user_tz)
        deadline_str = local_deadline.strftime("%d.%m.%Y в %H:%M")
        
        # Вычисляем время до дедлайна
        now = datetime.now(timezone.utc)
        time_left = deadline_ts - now
        
        if time_left.days > 0:
            time_left_str = f"{time_left.days} дн."
        elif time_left.seconds > 3600:
            hours = time_left.seconds // 3600
            time_left_str = f"{hours} ч."
        else:
            minutes = time_left.seconds // 60
            time_left_str = f"{minutes} мин."
        
        message = f"⏰ <b>Напоминание о дедлайне</b>\n\n"
        message += f"📚 <b>Предмет:</b> {subject.name}\n"
        
        # Задание с гиперссылкой, если есть ссылка
        if deadline.hw_name:
            if deadline.source_link:
                message += f"📝 <b>Задание:</b> <a href='{deadline.source_link}'>{deadline.hw_name}</a>\n"
            else:
                message += f"📝 <b>Задание:</b> {deadline.hw_name}\n"
        
        message += f"{deadline_type_icon} <b>Дедлайн:</b> {deadline_str} (Осталось {time_left_str})\n"
        
        if deadline.note:
            message += f"\n💬 <i>{deadline.note}</i>"
        
        return message

    
    
    def _format_multiple_notifications(self, notification_data: List[Dict[str, Any]], user_tz) -> str:
        """Форматировать множественные уведомления"""
        message = f"⏰ <b>Напоминания о дедлайнах ({len(notification_data)})</b>\n\n"
        
        # Сортируем по времени дедлайна
        notification_data.sort(key=lambda x: x['notification'].original_deadline_ts)
        
        for i, data in enumerate(notification_data, 1):
            notification = data['notification']
            deadline = data['deadline']
            subject = data['subject']
            
            deadline_type_icon = "🟡" if notification.deadline_type == 'soft' else "🔴"
            
            # Определяем какой дедлайн использовать
            if notification.deadline_type == 'soft':
                deadline_ts = deadline.soft_deadline_ts
            else:
                deadline_ts = deadline.hard_deadline_ts
            
            # Форматируем дату в TZ пользователя
            local_deadline = deadline_ts.astimezone(user_tz)
            deadline_str = local_deadline.strftime("%d.%m.%Y в %H:%M")
            
            # Вычисляем время до дедлайна
            now = datetime.now(timezone.utc)
            time_left = deadline_ts - now
            
            if time_left.days > 0:
                time_left_str = f"{time_left.days} дн."
            elif time_left.seconds > 3600:
                hours = time_left.seconds // 3600
                time_left_str = f"{hours} ч."
            else:
                minutes = time_left.seconds // 60
                time_left_str = f"{minutes} мин."
            
            message += f"<b>{i}. {subject.name}</b>\n"
            
            # Задание с гиперссылкой, если есть ссылка
            if deadline.hw_name:
                if deadline.source_link:
                    message += f"📝 <a href='{deadline.source_link}'>{deadline.hw_name}</a>\n"
                else:
                    message += f"📝 {deadline.hw_name}\n"
            
            message += f"{deadline_type_icon} <b>Дедлайн:</b> {deadline_str} (Осталось {time_left_str})\n"
            
            message += "\n"
        
        return message

# Создаем экземпляр сервиса
scheduled_notification_sender = ScheduledNotificationSender()
