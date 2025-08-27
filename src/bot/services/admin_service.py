import asyncio
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime, timedelta
from sqlalchemy import select, func
from aiogram import Bot
import pytz

from src.core.database import db_manager
from src.core.models import User, Deadline
from src.bot.services.subscription_service import subscription_service
from src.bot.services.notification_service import notification_service
from src.utils import get_logger

logger = get_logger()

class AdminService:
    """Сервис для административных функций"""
    
    def __init__(self):
        self.moscow_tz = pytz.timezone('Europe/Moscow')
    
    async def get_bot_statistics(self) -> Dict[str, Any]:
        """Получить основную статистику бота"""
        async with db_manager.async_session() as session:
            try:
                stats = {}
                
                # Общее количество пользователей
                stmt = select(func.count(User.tg_user_id))
                result = await session.execute(stmt)
                stats['total_users'] = result.scalar() or 0
                
                # Активные пользователи за неделю
                week_ago = datetime.now(self.moscow_tz) - timedelta(days=7)
                stmt = select(func.count(User.tg_user_id)).where(
                    User.last_activity_ts >= week_ago
                )
                result = await session.execute(stmt)
                stats['active_users_week'] = result.scalar() or 0
                
                # Активные пользователи за месяц
                month_ago = datetime.now(self.moscow_tz) - timedelta(days=30)
                stmt = select(func.count(User.tg_user_id)).where(
                    User.last_activity_ts >= month_ago
                )
                result = await session.execute(stmt)
                stats['active_users_month'] = result.scalar() or 0
                
                # Статистика подписок
                subscription_stats = await subscription_service.get_subscription_stats()
                stats.update(subscription_stats)
                
                # Статистика уведомлений
                notification_stats = await notification_service.get_notification_stats()
                stats.update(notification_stats)
                
                # Статистика дедлайнов
                stmt = select(func.count(Deadline.id))
                result = await session.execute(stmt)
                stats['total_deadlines'] = result.scalar() or 0
                
                # Активные дедлайны (в будущем)
                now = datetime.now(self.moscow_tz)
                stmt = select(func.count(Deadline.id)).where(
                    (Deadline.soft_deadline_ts >= now) | 
                    (Deadline.hard_deadline_ts >= now)
                )
                result = await session.execute(stmt)
                stats['active_deadlines'] = result.scalar() or 0
                
                # Дедлайны на неделю
                week_later = now + timedelta(days=7)
                stmt = select(func.count(Deadline.id)).where(
                    ((Deadline.soft_deadline_ts >= now) & (Deadline.soft_deadline_ts <= week_later)) |
                    ((Deadline.hard_deadline_ts >= now) & (Deadline.hard_deadline_ts <= week_later))
                )
                result = await session.execute(stmt)
                stats['deadlines_week'] = result.scalar() or 0
                
                # Информация о последней синхронизации
                # Это можно получить из логов или добавить отдельную таблицу
                stats['last_sync'] = "Недавно"  # Заглушка
                stats['sync_status'] = "Активна"  # Заглушка
                
                return stats
                
            except Exception as e:
                logger.error(f"Ошибка получения статистики: {e}")
                return {}
    
    async def get_detailed_statistics(self) -> Dict[str, Any]:
        """Получить подробную статистику"""
        async with db_manager.async_session() as session:
            try:
                stats = {}
                
                # Активность по дням (последние 7 дней)
                daily_activity = []
                for i in range(7):
                    date = datetime.now(self.moscow_tz) - timedelta(days=i)
                    start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
                    end_of_day = date.replace(hour=23, minute=59, second=59, microsecond=999999)
                    
                    stmt = select(func.count(User.tg_user_id.distinct())).where(
                        (User.last_activity_ts >= start_of_day) &
                        (User.last_activity_ts <= end_of_day)
                    )
                    result = await session.execute(stmt)
                    user_count = result.scalar() or 0
                    
                    daily_activity.append({
                        'date': date.strftime('%d.%m'),
                        'users': user_count
                    })
                
                stats['daily_activity'] = list(reversed(daily_activity))
                
                # Популярные настройки уведомлений
                notification_stats = await notification_service.get_notification_stats()
                stats['popular_notification_settings'] = notification_stats.get('popular_settings', [])
                
                return stats
                
            except Exception as e:
                logger.error(f"Ошибка получения подробной статистики: {e}")
                return {}
    
    async def get_active_users_count(self) -> int:
        """Получить количество активных пользователей для рассылки"""
        async with db_manager.async_session() as session:
            try:
                # Считаем пользователей, которые были активны в последний месяц
                month_ago = datetime.now(self.moscow_tz) - timedelta(days=30)
                stmt = select(func.count(User.tg_user_id)).where(
                    User.last_activity_ts >= month_ago
                )
                result = await session.execute(stmt)
                return result.scalar() or 0
                
            except Exception as e:
                logger.error(f"Ошибка получения количества активных пользователей: {e}")
                return 0
    
    async def get_users_for_broadcast(self) -> List[User]:
        """Получить список пользователей для рассылки"""
        async with db_manager.async_session() as session:
            try:
                # Получаем активных пользователей за последний месяц
                month_ago = datetime.now(self.moscow_tz) - timedelta(days=30)
                stmt = select(User).where(
                    User.last_activity_ts >= month_ago
                ).order_by(User.tg_user_id)
                
                result = await session.execute(stmt)
                return list(result.scalars().all())
                
            except Exception as e:
                logger.error(f"Ошибка получения пользователей для рассылки: {e}")
                return []
    
    async def send_broadcast(
        self, 
        message_text: str, 
        bot: Bot, 
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> Dict[str, int]:
        """Отправить массовую рассылку"""
        try:
            users = await self.get_users_for_broadcast()
            total_users = len(users)
            
            if total_users == 0:
                return {'success': 0, 'errors': 0}
            
            success_count = 0
            error_count = 0
            
            logger.info(f"Начинаю рассылку для {total_users} пользователей")
            
            # Отправляем сообщения с задержкой для избежания лимитов
            for i, user in enumerate(users, 1):
                try:
                    await bot.send_message(
                        chat_id=user.tg_user_id,
                        text=message_text,
                        parse_mode='HTML'
                    )
                    success_count += 1
                    
                    # Задержка между отправками (30 сообщений в секунду - лимит Telegram)
                    if i % 30 == 0:
                        await asyncio.sleep(1)
                    
                    # Обновляем прогресс каждые 10 сообщений
                    if progress_callback and i % 10 == 0:
                        progress_callback(i, total_users)
                        
                except Exception as e:
                    error_count += 1
                    logger.warning(f"Ошибка отправки пользователю {user.tg_user_id}: {e}")
                    
                    # Если пользователь заблокировал бота, можно пометить его как неактивного
                    if "bot was blocked" in str(e).lower():
                        # Можно добавить логику деактивации пользователя
                        pass
            
            logger.info(f"Рассылка завершена: {success_count} успешно, {error_count} ошибок")
            
            return {
                'success': success_count,
                'errors': error_count
            }
            
        except Exception as e:
            logger.error(f"Ошибка выполнения рассылки: {e}")
            return {'success': 0, 'errors': 0}
    
    async def get_user_info(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Получить подробную информацию о пользователе"""
        async with db_manager.async_session() as session:
            try:
                # Основная информация о пользователе
                stmt = select(User).where(User.tg_user_id == user_id)
                result = await session.execute(stmt)
                user = result.scalar_one_or_none()
                
                if not user:
                    return None
                
                # Подписки пользователя
                subscriptions = await subscription_service.get_user_subscriptions(user_id)
                
                # Настройки уведомлений
                notifications = await notification_service.get_user_notifications(user_id)
                
                return {
                    'user': user,
                    'subscriptions_count': len(subscriptions),
                    'subscriptions': subscriptions,
                    'notifications_count': len(notifications),
                    'notifications': notifications
                }
                
            except Exception as e:
                logger.error(f"Ошибка получения информации о пользователе {user_id}: {e}")
                return None
    
    async def cleanup_inactive_users(self, days_inactive: int = 90) -> int:
        """Очистка неактивных пользователей"""
        async with db_manager.async_session() as session:
            try:
                cutoff_date = datetime.now(self.moscow_tz) - timedelta(days=days_inactive)
                
                # Находим неактивных пользователей
                stmt = select(User).where(
                    (User.last_activity_ts < cutoff_date) |
                    (User.last_activity_ts.is_(None))
                )
                result = await session.execute(stmt)
                inactive_users = result.scalars().all()
                
                count = 0
                for user in inactive_users:
                    # Удаляем связанные данные (подписки, уведомления)
                    # Каскадное удаление должно работать автоматически
                    await session.delete(user)
                    count += 1
                
                await session.commit()
                logger.info(f"Удалено {count} неактивных пользователей")
                return count
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка очистки неактивных пользователей: {e}")
                return 0

# Создаем экземпляр сервиса
admin_service = AdminService()