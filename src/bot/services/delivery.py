"""
Сервис для обеспечения надежной доставки сообщений.
"""
import asyncio
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple
from enum import Enum
from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter,
    TelegramNetworkError, TelegramServerError
)

from src.db import get_db_session, SentNotificationCRUD, UserCRUD
from src.utils import notifications_logger, settings


class DeliveryStatus(Enum):
    """Статусы доставки сообщений."""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    BLOCKED = "blocked"
    RETRY = "retry"


class RetryStrategy(Enum):
    """Стратегии повторных попыток."""
    EXPONENTIAL_BACKOFF = "exponential_backoff"
    FIXED_INTERVAL = "fixed_interval"
    IMMEDIATE = "immediate"


class DeliveryService:
    """Сервис для обеспечения надежной доставки сообщений."""
    
    def __init__(self, bot: Bot):
        self.bot = bot
        self.logger = notifications_logger
        self.max_retries = settings.notification_retry_attempts
        self.retry_delays = [1, 5, 15, 60, 300]  # секунды: 1с, 5с, 15с, 1м, 5м
        self.batch_size = settings.notification_batch_size
        self.rate_limit_delay = 1.0 / settings.telegram_rate_limit  # секунд между сообщениями
    
    async def send_message_with_retry(
        self,
        chat_id: int,
        text: str,
        reply_markup=None,
        parse_mode: str = 'HTML',
        notification_id: Optional[int] = None,
        retry_strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_BACKOFF
    ) -> Tuple[bool, Optional[int], Optional[str]]:
        """
        Отправляет сообщение с механизмом повторных попыток.
        
        Args:
            chat_id: ID чата
            text: Текст сообщения
            reply_markup: Клавиатура
            parse_mode: Режим парсинга
            notification_id: ID уведомления в БД
            retry_strategy: Стратегия повторных попыток
            
        Returns:
            Tuple[success, message_id, error_message]
        """
        last_error = None
        
        for attempt in range(self.max_retries + 1):
            try:
                # Отправляем сообщение
                message = await self.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
                
                # Обновляем статус в БД
                if notification_id:
                    await self._update_notification_status(
                        notification_id, DeliveryStatus.SENT, message.message_id
                    )
                
                self.logger.info(
                    f"Message sent successfully to {chat_id}",
                    chat_id=chat_id,
                    message_id=message.message_id,
                    attempt=attempt + 1
                )
                
                return True, message.message_id, None
                
            except TelegramForbiddenError as e:
                # Пользователь заблокировал бота
                await self._handle_blocked_user(chat_id, notification_id)
                return False, None, f"User blocked bot: {str(e)}"
                
            except TelegramRetryAfter as e:
                # Rate limit - ждем указанное время
                wait_time = e.retry_after
                self.logger.warning(
                    f"Rate limit hit, waiting {wait_time}s",
                    chat_id=chat_id,
                    wait_time=wait_time,
                    attempt=attempt + 1
                )
                await asyncio.sleep(wait_time)
                continue
                
            except (TelegramNetworkError, TelegramServerError) as e:
                # Сетевые ошибки или ошибки сервера - можно повторить
                last_error = str(e)
                self.logger.warning(
                    f"Network/Server error on attempt {attempt + 1}: {last_error}",
                    chat_id=chat_id,
                    attempt=attempt + 1,
                    error=last_error
                )
                
                if attempt < self.max_retries:
                    delay = self._calculate_retry_delay(attempt, retry_strategy)
                    await asyncio.sleep(delay)
                    continue
                
            except TelegramBadRequest as e:
                # Ошибка в запросе - не повторяем
                last_error = f"Bad request: {str(e)}"
                self.logger.error(
                    f"Bad request error: {last_error}",
                    chat_id=chat_id,
                    text_preview=text[:100]
                )
                break
                
            except Exception as e:
                # Другие ошибки
                last_error = f"Unexpected error: {str(e)}"
                self.logger.error(
                    f"Unexpected error on attempt {attempt + 1}: {last_error}",
                    chat_id=chat_id,
                    attempt=attempt + 1
                )
                
                if attempt < self.max_retries:
                    delay = self._calculate_retry_delay(attempt, retry_strategy)
                    await asyncio.sleep(delay)
                    continue
                break
        
        # Все попытки исчерпаны
        if notification_id:
            await self._update_notification_status(
                notification_id, DeliveryStatus.FAILED, error_message=last_error
            )
        
        self.logger.error(
            f"Failed to send message after {self.max_retries + 1} attempts",
            chat_id=chat_id,
            final_error=last_error
        )
        
        return False, None, last_error
    
    def _calculate_retry_delay(self, attempt: int, strategy: RetryStrategy) -> float:
        """
        Вычисляет задержку перед повторной попыткой.
        
        Args:
            attempt: Номер попытки (начиная с 0)
            strategy: Стратегия повторных попыток
            
        Returns:
            Задержка в секундах
        """
        if strategy == RetryStrategy.IMMEDIATE:
            return 0.1
        elif strategy == RetryStrategy.FIXED_INTERVAL:
            return 5.0
        elif strategy == RetryStrategy.EXPONENTIAL_BACKOFF:
            if attempt < len(self.retry_delays):
                return self.retry_delays[attempt]
            else:
                # Для попыток сверх предустановленных используем максимальную задержку
                return self.retry_delays[-1]
        else:
            return 1.0
    
    async def _update_notification_status(
        self,
        notification_id: int,
        status: DeliveryStatus,
        message_id: Optional[int] = None,
        error_message: Optional[str] = None
    ):
        """
        Обновляет статус уведомления в базе данных.
        
        Args:
            notification_id: ID уведомления
            status: Новый статус
            message_id: ID сообщения в Telegram
            error_message: Сообщение об ошибке
        """
        try:
            async with get_db_session() as session:
                update_data = {'status': status.value}
                
                if message_id:
                    update_data['message_id'] = message_id
                
                if error_message:
                    update_data['error_message'] = error_message
                
                if status == DeliveryStatus.DELIVERED:
                    update_data['delivered_at'] = datetime.now(timezone.utc)
                
                await SentNotificationCRUD.update_status(
                    session, notification_id, **update_data
                )
                
        except Exception as e:
            self.logger.error(f"Error updating notification status: {e}")
    
    async def _handle_blocked_user(self, chat_id: int, notification_id: Optional[int] = None):
        """
        Обрабатывает случай, когда пользователь заблокировал бота.
        
        Args:
            chat_id: ID чата (telegram_id пользователя)
            notification_id: ID уведомления
        """
        try:
            async with get_db_session() as session:
                # Помечаем пользователя как заблокированного
                await UserCRUD.set_blocked(session, chat_id, True)
                
                # Обновляем статус уведомления
                if notification_id:
                    await self._update_notification_status(
                        notification_id, DeliveryStatus.BLOCKED
                    )
                
                self.logger.info(f"User {chat_id} marked as blocked")
                
        except Exception as e:
            self.logger.error(f"Error handling blocked user: {e}")
    
    async def send_batch_with_rate_limiting(
        self,
        messages: List[Dict],
        retry_strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_BACKOFF
    ) -> Dict[str, int]:
        """
        Отправляет батч сообщений с соблюдением rate limits.
        
        Args:
            messages: Список сообщений для отправки
            retry_strategy: Стратегия повторных попыток
            
        Returns:
            Статистика отправки
        """
        stats = {
            'total': len(messages),
            'sent': 0,
            'failed': 0,
            'blocked': 0
        }
        
        # Разбиваем на батчи
        for i in range(0, len(messages), self.batch_size):
            batch = messages[i:i + self.batch_size]
            
            # Отправляем сообщения в батче
            for j, msg_data in enumerate(batch):
                try:
                    success, message_id, error = await self.send_message_with_retry(
                        chat_id=msg_data['chat_id'],
                        text=msg_data['text'],
                        reply_markup=msg_data.get('reply_markup'),
                        parse_mode=msg_data.get('parse_mode', 'HTML'),
                        notification_id=msg_data.get('notification_id'),
                        retry_strategy=retry_strategy
                    )
                    
                    if success:
                        stats['sent'] += 1
                    elif error and 'blocked' in error.lower():
                        stats['blocked'] += 1
                    else:
                        stats['failed'] += 1
                    
                    # Соблюдаем rate limit между сообщениями
                    if j < len(batch) - 1:  # Не ждем после последнего сообщения в батче
                        await asyncio.sleep(self.rate_limit_delay)
                        
                except Exception as e:
                    self.logger.error(f"Error sending message in batch: {e}")
                    stats['failed'] += 1
            
            # Пауза между батчами
            if i + self.batch_size < len(messages):
                await asyncio.sleep(1.0)
        
        self.logger.info(
            "Batch sending completed",
            **stats
        )
        
        return stats
    
    async def retry_failed_notifications(self, hours_back: int = 24) -> Dict[str, int]:
        """
        Повторно отправляет неудачные уведомления.
        
        Args:
            hours_back: За сколько часов назад искать неудачные уведомления
            
        Returns:
            Статистика повторной отправки
        """
        stats = {
            'found': 0,
            'retried': 0,
            'success': 0,
            'failed': 0
        }
        
        try:
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours_back)
            
            async with get_db_session() as session:
                # TODO: Реализовать метод для получения неудачных уведомлений
                # failed_notifications = await SentNotificationCRUD.get_failed_notifications(
                #     session, cutoff_time, max_retry_count=self.max_retries
                # )
                
                # stats['found'] = len(failed_notifications)
                
                # for notification in failed_notifications:
                #     try:
                #         # Формируем сообщение заново
                #         message_text = self._reconstruct_notification_message(notification)
                #         
                #         success, message_id, error = await self.send_message_with_retry(
                #             chat_id=notification.user.telegram_id,
                #             text=message_text,
                #             notification_id=notification.id,
                #             retry_strategy=RetryStrategy.EXPONENTIAL_BACKOFF
                #         )
                #         
                #         stats['retried'] += 1
                #         
                #         if success:
                #             stats['success'] += 1
                #         else:
                #             stats['failed'] += 1
                #             
                #     except Exception as e:
                #         self.logger.error(f"Error retrying notification {notification.id}: {e}")
                #         stats['failed'] += 1
                
                self.logger.info("Failed notifications retry completed", **stats)
                
        except Exception as e:
            self.logger.error(f"Error in retry_failed_notifications: {e}")
        
        return stats
    
    async def check_delivery_status(self, hours_back: int = 1) -> Dict[str, int]:
        """
        Проверяет статус доставки недавних сообщений.
        
        Args:
            hours_back: За сколько часов назад проверять
            
        Returns:
            Статистика доставки
        """
        stats = {
            'total_checked': 0,
            'delivered': 0,
            'pending': 0,
            'failed': 0,
            'blocked': 0
        }
        
        try:
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours_back)
            
            async with get_db_session() as session:
                # TODO: Реализовать метод для получения недавних уведомлений
                # recent_notifications = await SentNotificationCRUD.get_recent_notifications(
                #     session, cutoff_time
                # )
                
                # stats['total_checked'] = len(recent_notifications)
                
                # for notification in recent_notifications:
                #     if notification.status == 'sent':
                #         # Проверяем, доставлено ли сообщение
                #         # В Telegram Bot API нет прямого способа проверить доставку,
                #         # но можно использовать косвенные признаки
                #         stats['delivered'] += 1
                #     elif notification.status == 'pending':
                #         stats['pending'] += 1
                #     elif notification.status == 'failed':
                #         stats['failed'] += 1
                #     elif notification.status == 'blocked':
                #         stats['blocked'] += 1
                
                self.logger.info("Delivery status check completed", **stats)
                
        except Exception as e:
            self.logger.error(f"Error checking delivery status: {e}")
        
        return stats
    
    def _reconstruct_notification_message(self, notification) -> str:
        """
        Восстанавливает текст уведомления для повторной отправки.
        
        Args:
            notification: Объект уведомления из БД
            
        Returns:
            Восстановленный текст сообщения
        """
        # TODO: Реализовать восстановление сообщения на основе данных из БД
        # Это может потребовать сохранения дополнительной информации в БД
        # или повторного формирования сообщения на основе deadline
        
        return f"🔄 Повторная отправка уведомления (ID: {notification.id})"
    
    async def get_delivery_statistics(self, days_back: int = 7) -> Dict:
        """
        Получает статистику доставки за указанный период.
        
        Args:
            days_back: За сколько дней назад собирать статистику
            
        Returns:
            Детальная статистика доставки
        """
        try:
            cutoff_time = datetime.now(timezone.utc) - timedelta(days=days_back)
            
            async with get_db_session() as session:
                # TODO: Реализовать получение статистики доставки
                stats = {
                    'period_days': days_back,
                    'total_notifications': 0,
                    'successful_deliveries': 0,
                    'failed_deliveries': 0,
                    'blocked_users': 0,
                    'retry_attempts': 0,
                    'delivery_rate': 0.0,
                    'average_retry_count': 0.0
                }
                
                # delivery_stats = await SentNotificationCRUD.get_delivery_statistics(
                #     session, cutoff_time
                # )
                # stats.update(delivery_stats)
                
                return stats
                
        except Exception as e:
            self.logger.error(f"Error getting delivery statistics: {e}")
            return {}