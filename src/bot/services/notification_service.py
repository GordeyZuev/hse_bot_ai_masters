from typing import List, Optional, Tuple
from sqlalchemy import select, delete, update
from datetime import datetime
import pytz

from src.core.database import db_manager
from src.core.models import User, UserNotification
from src.utils import get_logger

logger = get_logger()

class NotificationService:
    """Сервис для работы с настройками уведомлений пользователей"""
    
    def __init__(self):
        self.moscow_tz = pytz.timezone('Europe/Moscow')
    
    async def get_user_notifications(self, user_id: int) -> List[UserNotification]:
        """Получить настройки уведомлений пользователя"""
        async with db_manager.async_session() as session:
            try:
                stmt = select(UserNotification).where(
                    UserNotification.user_id == user_id
                ).order_by(UserNotification.notification_number)
                
                result = await session.execute(stmt)
                return list(result.scalars().all())
                
            except Exception as e:
                logger.error(f"Ошибка получения уведомлений пользователя {user_id}: {e}")
                return []
    
    async def set_user_notification(
        self, 
        user_id: int, 
        notification_number: int, 
        offset_value: int, 
        offset_unit: str
    ) -> Tuple[bool, str]:
        """Установить настройки уведомления для пользователя"""
        async with db_manager.async_session() as session:
            try:
                # Проверяем валидность параметров
                if notification_number not in [1, 2]:
                    return False, "Номер уведомления должен быть 1 или 2"
                
                if offset_unit not in ['days', 'hours', 'minutes']:
                    return False, "Единица времени должна быть: days, hours или minutes"
                
                if offset_value <= 0:
                    return False, "Значение времени должно быть положительным"
                
                # Ищем существующее уведомление
                stmt = select(UserNotification).where(
                    UserNotification.user_id == user_id,
                    UserNotification.notification_number == notification_number
                )
                result = await session.execute(stmt)
                notification = result.scalar_one_or_none()
                
                current_time = datetime.now(self.moscow_tz)
                
                if notification:
                    # Обновляем существующее
                    notification.offset_value = offset_value
                    notification.offset_unit = offset_unit
                    notification.is_enabled = True
                    notification.last_modified = current_time
                else:
                    # Создаем новое
                    notification = UserNotification(
                        user_id=user_id,
                        notification_number=notification_number,
                        offset_value=offset_value,
                        offset_unit=offset_unit,
                        is_enabled=True
                    )
                    session.add(notification)
                
                await session.commit()
                
                unit_text = {
                    'days': 'дн.',
                    'hours': 'ч.',
                    'minutes': 'мин.'
                }.get(offset_unit, offset_unit)
                
                logger.info(f"Пользователь {user_id} настроил уведомление {notification_number}: за {offset_value} {unit_text}")
                return True, f"Уведомление настроено: за {offset_value} {unit_text}"
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка настройки уведомления для пользователя {user_id}: {e}")
                return False, "Произошла ошибка при настройке уведомления"
    
    async def toggle_notification(
        self, 
        user_id: int, 
        notification_number: int, 
        is_enabled: bool
    ) -> Tuple[bool, str]:
        """Включить/выключить уведомление"""
        async with db_manager.async_session() as session:
            try:
                stmt = select(UserNotification).where(
                    UserNotification.user_id == user_id,
                    UserNotification.notification_number == notification_number
                )
                result = await session.execute(stmt)
                notification = result.scalar_one_or_none()
                
                if not notification:
                    return False, "Уведомление не найдено. Сначала настройте его."
                
                notification.is_enabled = is_enabled
                notification.last_modified = datetime.now(self.moscow_tz)
                
                await session.commit()
                
                status_text = "включено" if is_enabled else "выключено"
                logger.info(f"Пользователь {user_id} {status_text} уведомление {notification_number}")
                return True, f"Уведомление {notification_number} {status_text}"
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка переключения уведомления для пользователя {user_id}: {e}")
                return False, "Произошла ошибка при изменении настроек"
    
    async def reset_user_notifications(self, user_id: int) -> Tuple[bool, str]:
        """Сбросить все настройки уведомлений пользователя"""
        async with db_manager.async_session() as session:
            try:
                stmt = delete(UserNotification).where(UserNotification.user_id == user_id)
                result = await session.execute(stmt)
                await session.commit()
                
                count = result.rowcount
                if count > 0:
                    logger.info(f"Пользователь {user_id} сбросил {count} настроек уведомлений")
                    return True, f"Сброшено {count} настроек уведомлений"
                else:
                    return True, "Настройки уведомлений уже сброшены"
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка сброса уведомлений для пользователя {user_id}: {e}")
                return False, "Произошла ошибка при сбросе настроек"
    
    async def get_users_for_notification(self, hours_before: int) -> List[dict]:
        """Получить пользователей, которым нужно отправить уведомления"""
        async with db_manager.async_session() as session:
            try:
                # Получаем всех пользователей с активными уведомлениями
                stmt = select(User, UserNotification).join(UserNotification).where(
                    UserNotification.is_enabled == True
                )
                result = await session.execute(stmt)
                
                users_notifications = []
                for user, notification in result.fetchall():
                    # Конвертируем offset в часы для сравнения
                    offset_hours = self._convert_to_hours(notification.offset_value, notification.offset_unit)
                    
                    # Проверяем, подходит ли это уведомление для текущего времени
                    if abs(offset_hours - hours_before) <= 1:  # Допуск в 1 час
                        users_notifications.append({
                            'user': user,
                            'notification': notification,
                            'offset_hours': offset_hours
                        })
                
                return users_notifications
                
            except Exception as e:
                logger.error(f"Ошибка получения пользователей для уведомлений: {e}")
                return []
    
    def _convert_to_hours(self, offset_value: int, offset_unit: str) -> float:
        """Конвертировать offset в часы"""
        if offset_unit == 'hours':
            return float(offset_value)
        elif offset_unit == 'days':
            return float(offset_value * 24)
        elif offset_unit == 'minutes':
            return float(offset_value / 60)
        else:
            return 0.0
    
    async def get_notification_stats(self) -> dict:
        """Получить статистику настроек уведомлений"""
        async with db_manager.async_session() as session:
            try:
                # Общее количество настроек
                stmt = select(UserNotification)
                result = await session.execute(stmt)
                total_notifications = len(result.scalars().all())
                
                # Активные настройки
                stmt = select(UserNotification).where(UserNotification.is_enabled == True)
                result = await session.execute(stmt)
                active_notifications = len(result.scalars().all())
                
                # Пользователи с настройками
                stmt = select(UserNotification.user_id).distinct()
                result = await session.execute(stmt)
                users_with_notifications = len(result.scalars().all())
                
                # Популярные настройки
                from sqlalchemy import func
                stmt = select(
                    UserNotification.offset_value,
                    UserNotification.offset_unit,
                    func.count().label('count')
                ).where(
                    UserNotification.is_enabled == True
                ).group_by(
                    UserNotification.offset_value,
                    UserNotification.offset_unit
                ).order_by(func.count().desc()).limit(5)
                
                result = await session.execute(stmt)
                popular_settings = result.all()
                
                return {
                    'total_notifications': total_notifications,
                    'active_notifications': active_notifications,
                    'users_with_notifications': users_with_notifications,
                    'popular_settings': popular_settings
                }
                
            except Exception as e:
                logger.error(f"Ошибка получения статистики уведомлений: {e}")
                return {}

# Создаем экземпляр сервиса
notification_service = NotificationService()