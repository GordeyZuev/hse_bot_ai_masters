from typing import List, Tuple, Dict, Any
from sqlalchemy import select
from datetime import datetime
import pytz

from src.core.database import db_manager
from src.core.models import User, UserNotificationSettings
from src.bot.services.notification_scheduler_service import notification_scheduler_service
from src.utils import get_logger
from sqlalchemy import func

logger = get_logger()

class NotificationService:
    """Сервис для работы с настройками уведомлений пользователей"""
    
    def __init__(self):
        self.moscow_tz = pytz.timezone('Europe/Moscow')
    
    async def get_user_notification_settings(self, user_id: int) -> UserNotificationSettings:
        """Получить настройки уведомлений пользователя"""
        try:
            return await db_manager.get_user_notification_settings(user_id)
        except Exception as e:
            logger.error(f"Ошибка получения настроек уведомлений пользователя {user_id}: {e}")
            return await db_manager.create_user_notification_settings(user_id)
    
    async def set_user_notification(
        self,
        user_id: int,
        notification_number: int,
        offset_value: int,
        offset_unit: str
    ) -> Tuple[bool, str]:
        """Установить настройки уведомления для пользователя"""
        try:
            # Проверяем валидность параметров
            if notification_number not in [1, 2]:
                return False, "Номер уведомления должен быть 1 или 2"
            
            if offset_unit not in ['days', 'hours']:
                return False, "Единица времени должна быть: days или hours"
            
            if offset_value <= 0:
                return False, "Значение времени должно быть положительным"
            
            # Проверяем минимальное время уведомления (1 час)
            total_hours = self._convert_to_hours(offset_value, offset_unit)
            if total_hours < 1:
                return False, "Минимальное время уведомления - 1 час"
            
            # Готовим данные для обновления
            if notification_number == 1:
                settings_data = {
                    'reminder1_offset': offset_value,
                    'reminder1_unit': offset_unit
                }
            else:
                settings_data = {
                    'reminder2_offset': offset_value,
                    'reminder2_unit': offset_unit
                }
            
            # Обновляем настройки
            await db_manager.update_user_notification_settings(user_id, settings_data)
            
            # Перепланируем уведомления пользователя
            rescheduled_count = await notification_scheduler_service.reschedule_notifications_for_user_settings_change(user_id)
            
            unit_text = {
                'days': 'дн.',
                'hours': 'ч.'
            }.get(offset_unit, offset_unit)
            
            logger.info(f"Пользователь {user_id} настроил уведомление {notification_number}: за {offset_value} {unit_text}. Перепланировано {rescheduled_count} уведомлений")
            return True, f"Уведомление настроено: за {offset_value} {unit_text}"
            
        except Exception as e:
            logger.error(f"Ошибка настройки уведомления для пользователя {user_id}: {e}")
            return False, "Произошла ошибка при настройке уведомления"
    
    async def toggle_notifications(self, user_id: int, is_enabled: bool) -> Tuple[bool, str]:
        """Включить/выключить все уведомления пользователя"""
        try:
            settings_data = {'is_active': is_enabled}
            await db_manager.update_user_notification_settings(user_id, settings_data)
            
            if is_enabled:
                # Если включаем уведомления, перепланируем их
                rescheduled_count = await notification_scheduler_service.reschedule_notifications_for_user_settings_change(user_id)
                status_text = "включены"
                logger.info(f"Пользователь {user_id} включил уведомления. Запланировано {rescheduled_count} уведомлений")
            else:
                # Если выключаем, отменяем все запланированные уведомления пользователя
                async with db_manager.async_session() as session:
                    from src.core.models import ScheduledNotification
                    from sqlalchemy import and_
                    
                    stmt = select(ScheduledNotification).where(
                        and_(
                            ScheduledNotification.user_id == user_id,
                            ScheduledNotification.status == 'scheduled'
                        )
                    )
                    result = await session.execute(stmt)
                    notifications = result.scalars().all()
                    
                    cancelled_count = 0
                    for notification in notifications:
                        notification.status = 'cancelled'
                        notification.updated_at = datetime.now(self.moscow_tz)
                        cancelled_count += 1
                    
                    await session.commit()
                
                status_text = "выключены"
                logger.info(f"Пользователь {user_id} выключил уведомления. Отменено {cancelled_count} уведомлений")
            
            return True, f"Уведомления {status_text}"
            
        except Exception as e:
            logger.error(f"Ошибка переключения уведомлений для пользователя {user_id}: {e}")
            return False, "Произошла ошибка при изменении настроек"
    
    def _convert_to_hours(self, offset_value: int, offset_unit: str) -> int:
        """Конвертировать offset в часы"""
        if offset_unit == 'hours':
            return offset_value
        elif offset_unit == 'days':
            return offset_value * 24
        else:
            return 0
    

# Создаем экземпляр сервиса
notification_service = NotificationService()