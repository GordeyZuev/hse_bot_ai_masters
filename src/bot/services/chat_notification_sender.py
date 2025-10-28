import asyncio
from datetime import UTC, datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import and_, select
from sqlalchemy.orm import selectinload

from src.core.database import db_manager
from src.core.models import ChatScheduledNotification, Deadline
from src.utils import get_logger


logger = get_logger()


class ChatNotificationSender:
    """Сервис для отправки уведомлений в чаты"""

    def __init__(self):
        pass

    async def send_scheduled_chat_notifications(self, bot: Bot) -> dict[str, int]:
        """Отправить запланированные уведомления в чаты"""
        stats = {"sent": 0, "failed": 0, "skipped": 0, "total_processed": 0}

        try:
            logger.info("Проверка уведомлений для чатов")

            # Получаем уведомления для отправки (в течение ближайших 5 минут)
            notifications = await self._get_scheduled_notifications_for_delivery()

            if not notifications:
                logger.info("Нет уведомлений для чатов")
                return stats

            logger.info(f"Найдено {len(notifications)} уведомлений для чатов")

            # Группируем уведомления по чатам
            chat_notifications = self._group_notifications_by_chat(notifications)

            # Обрабатываем чаты батчами
            batch_size = 5
            chat_items = list(chat_notifications.items())

            for i in range(0, len(chat_items), batch_size):
                batch = chat_items[i : i + batch_size]

                # Обрабатываем батч параллельно
                tasks = []
                for chat_id, chat_notifs in batch:
                    task = self._process_chat_notifications(
                        bot, chat_id, chat_notifs, stats
                    )
                    tasks.append(task)

                await asyncio.gather(*tasks, return_exceptions=True)

            logger.info(f"Отправка в чаты завершена: {stats}")
            return stats

        except Exception as e:
            logger.error(f"Критическая ошибка при отправке уведомлений в чаты: {e}")
            return stats

    async def _get_scheduled_notifications_for_delivery(self) -> list[ChatScheduledNotification]:
        """Получить уведомления для отправки"""
        async with db_manager.async_session() as session:
            now = datetime.now(UTC)
            time_window = now + timedelta(minutes=5)

            stmt = (
                select(ChatScheduledNotification)
                .options(
                    selectinload(ChatScheduledNotification.chat_group),
                    selectinload(ChatScheduledNotification.deadline)
                )
                .where(
                    and_(
                        ChatScheduledNotification.status == "scheduled",
                        ChatScheduledNotification.planned_delivery_time <= time_window,
                        ChatScheduledNotification.planned_delivery_time >= now
                    )
                )
            )

            result = await session.execute(stmt)
            return list(result.scalars().all())

    def _group_notifications_by_chat(
        self, notifications: list[ChatScheduledNotification]
    ) -> dict[int, list[ChatScheduledNotification]]:
        """Группировать уведомления по чатам"""
        grouped = {}
        for notification in notifications:
            chat_id = notification.chat_group_id
            if chat_id not in grouped:
                grouped[chat_id] = []
            grouped[chat_id].append(notification)
        return grouped

    async def _process_chat_notifications(
        self,
        bot: Bot,
        chat_id: int,
        notifications: list[ChatScheduledNotification],
        stats: dict[str, int]
    ):
        """Обработать уведомления для одного чата"""
        try:
            # Проверяем, активен ли чат
            chat_group = notifications[0].chat_group
            if not chat_group.is_active:
                logger.info(f"Чат {chat_id} неактивен, пропускаем")
                stats["skipped"] += len(notifications)
                return

            # Группируем уведомления по дедлайнам
            deadline_notifications = self._group_notifications_by_deadline(notifications)

            # Отправляем уведомления
            for _deadline_id, deadline_notifs in deadline_notifications.items():
                success = await self._send_chat_notification(
                    bot, chat_id, deadline_notifs
                )

                if success:
                    stats["sent"] += len(deadline_notifs)
                    await self._mark_notifications_as_sent(deadline_notifs)
                else:
                    stats["failed"] += len(deadline_notifs)
                    await self._mark_notifications_as_failed(deadline_notifs)

                stats["total_processed"] += len(deadline_notifs)

        except Exception as e:
            logger.error(f"Ошибка обработки уведомлений для чата {chat_id}: {e}")
            stats["failed"] += len(notifications)
            stats["total_processed"] += len(notifications)

    def _group_notifications_by_deadline(
        self, notifications: list[ChatScheduledNotification]
    ) -> dict[int, list[ChatScheduledNotification]]:
        """Группировать уведомления по дедлайнам"""
        grouped = {}
        for notification in notifications:
            deadline_id = notification.deadline_id
            if deadline_id not in grouped:
                grouped[deadline_id] = []
            grouped[deadline_id].append(notification)
        return grouped

    async def _send_chat_notification(
        self,
        bot: Bot,
        chat_id: int,
        notifications: list[ChatScheduledNotification]
    ) -> bool:
        """Отправить уведомление в чат"""
        try:
            if not notifications:
                return False

            # Формируем сообщение
            message_text = self._format_chat_notification_message(notifications)

            # Создаем клавиатуру
            keyboard = self._create_chat_notification_keyboard(notifications[0].deadline)

            # Получаем topic_id для отправки в топик
            chat_group = notifications[0].chat_group
            message_thread_id = chat_group.topic_id

            # Отправляем сообщение
            await bot.send_message(
                chat_id=chat_id,
                text=message_text,
                reply_markup=keyboard,
                parse_mode="HTML",
                message_thread_id=message_thread_id
            )

            logger.info(f"Уведомление отправлено в чат {chat_id}" + (f" (топик {message_thread_id})" if message_thread_id else ""))
            return True

        except TelegramForbiddenError:
            logger.warning(f"Бот заблокирован в чате {chat_id}")
            return False
        except TelegramBadRequest as e:
            logger.error(f"Ошибка отправки в чат {chat_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Неожиданная ошибка отправки в чат {chat_id}: {e}")
            return False

    def _format_chat_notification_message(
        self, notifications: list[ChatScheduledNotification]
    ) -> str:
        """Форматировать сообщение уведомления"""
        if not notifications:
            return ""

        deadline = notifications[0].deadline
        subject = deadline.subject

        # Определяем тип дедлайна
        deadline_type = notifications[0].deadline_type
        deadline_emoji = "🟡" if deadline_type == "soft" else "🔴"
        deadline_text = "мягкий" if deadline_type == "soft" else "жёсткий"

        # Формируем текст
        text = f"{deadline_emoji} <b>Напоминание о дедлайне</b>\n\n"
        text += f"📚 <b>Предмет:</b> {subject.name}\n"
        text += f"📝 <b>Задание:</b> {deadline.hw_name or 'Не указано'}\n"
        text += f"⏰ <b>Дедлайн ({deadline_text}):</b> "

        if deadline_type == "soft":
            deadline_ts = deadline.soft_deadline_ts
        else:
            deadline_ts = deadline.hard_deadline_ts

        # Форматируем время (в часовом поясе Москвы)
        from src.utils.time import format_datetime_for_user
        formatted_time = format_datetime_for_user(deadline_ts, "Europe/Moscow")
        text += f"{formatted_time}\n"

        if deadline.note:
            text += f"📄 <b>Примечание:</b> {deadline.note}\n"

        if deadline.source_link:
            text += f"🔗 <b>Ссылка:</b> {deadline.source_link}\n"

        return text

    def _create_chat_notification_keyboard(self, deadline: Deadline) -> InlineKeyboardMarkup:
        """Создать клавиатуру для уведомления"""
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])

        if deadline.source_link:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text="🔗 Открыть ссылку", url=deadline.source_link)
            ])

        return keyboard

    async def _mark_notifications_as_sent(self, notifications: list[ChatScheduledNotification]):
        """Отметить уведомления как отправленные"""
        async with db_manager.async_session() as session:
            for notification in notifications:
                notification.status = "sent"
                notification.updated_at = datetime.now(UTC)
                session.add(notification)
            await session.commit()

    async def _mark_notifications_as_failed(self, notifications: list[ChatScheduledNotification]):
        """Отметить уведомления как неудачные"""
        async with db_manager.async_session() as session:
            for notification in notifications:
                notification.status = "failed"
                notification.updated_at = datetime.now(UTC)
                session.add(notification)
            await session.commit()


# Создаем экземпляр сервиса
chat_notification_sender = ChatNotificationSender()
