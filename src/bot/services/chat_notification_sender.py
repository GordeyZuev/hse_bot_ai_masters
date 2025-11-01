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

            # Группируем уведомления по чатам
            chat_notifications = self._group_notifications_by_chat(notifications)
            logger.debug(f"Уведомления разбиты по {len(chat_notifications)} чатам: {[(cid, len(notifs)) for cid, notifs in chat_notifications.items()]}")

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

            return stats

        except Exception as e:
            logger.error(f"Ошибка отправки уведомлений в чаты: {e}")
            return stats

    async def _get_scheduled_notifications_for_delivery(self) -> list[ChatScheduledNotification]:
        """Получить уведомления для отправки"""
        async with db_manager.async_session() as session:
            from src.core.models.models import ChatGroup

            now = datetime.now(UTC)
            time_window = now + timedelta(minutes=5)

            logger.debug(f"Поиск уведомлений для чатов: now={now}, window={time_window}")

            stmt = (
                select(ChatScheduledNotification)
                .join(ChatGroup)
                .options(
                    selectinload(ChatScheduledNotification.chat_group),
                    selectinload(ChatScheduledNotification.deadline)
                )
                .where(
                    and_(
                        ChatScheduledNotification.status == "scheduled",
                        ChatScheduledNotification.planned_delivery_time <= time_window,
                        ChatGroup.is_active,
                    )
                )
                .order_by(ChatScheduledNotification.planned_delivery_time)
            )

            result = await session.execute(stmt)
            notifications = list(result.scalars().all())
            logger.debug(f"Найдено {len(notifications)} активных уведомлений для чатов")
            return notifications

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
                stats["skipped"] += len(notifications)
                return

            # Группируем уведомления по дедлайнам
            deadline_notifications = self._group_notifications_by_deadline(notifications)

            # Формируем единое сообщение (как в scheduled_notification_sender)
            batch_text = self._format_multiple_notifications(deadline_notifications)

            # Получаем topic_id для отправки в топик
            message_thread_id = chat_group.topic_id

            # Отправляем единое сообщение для всех дедлайнов этого окна
            sent_ok = await self._safe_send_batch(
                bot, chat_id, batch_text, message_thread_id
            )

            if sent_ok:
                stats["sent"] += len(notifications)
                stats["total_processed"] += len(notifications)
                await self._mark_notifications_as_sent(list(notifications))
            else:
                stats["failed"] += len(notifications)
                stats["total_processed"] += len(notifications)
                await self._mark_notifications_as_failed(list(notifications))

        except Exception as e:
            logger.error(f"(C) {chat_id} - Ошибка обработки: {e}")
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

    async def _safe_send_batch(
        self, bot: Bot, chat_id: int, text: str, message_thread_id: int | None
    ) -> bool:
        try:
            if not text.strip():
                return False
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                message_thread_id=message_thread_id,
                disable_web_page_preview=True,
            )
            logger.info(f"(C) {chat_id} - Уведомление отправлено")
            return True
        except TelegramForbiddenError:
            logger.warning(f"(C) {chat_id} - Заблокирован")
            return False
        except TelegramBadRequest as e:
            logger.error(f"(C) {chat_id} - Ошибка: {e}")
            return False
        except Exception as e:
            logger.error(f"(C) {chat_id} - Ошибка: {e}")
            return False

    def _format_multiple_notifications(
        self, deadline_notifications: dict[int, list[ChatScheduledNotification]]
    ) -> str:
        """Сформировать единое сообщение для нескольких дедлайнов (DRY/KISS, как в scheduled)."""
        if not deadline_notifications:
            return ""

        # Количество уникальных заданий (дедлайнов)
        total_deadlines = len(deadline_notifications)
        lines: list[str] = []
        lines.append(f"⏰ <b>Напоминания о дедлайнах ({total_deadlines})</b>\n\n")

        from datetime import UTC, datetime

        from src.utils.notification_formatting import (
            format_deadline_datetime,
            format_time_remaining,
        )

        now = datetime.now(UTC)

        # Стабильный порядок: по ближайшему planned_delivery_time в группе
        items = []
        for _deadline_id, notifs in deadline_notifications.items():
            earliest_planned = min(n.planned_delivery_time for n in notifs)
            items.append((earliest_planned, notifs))
        items.sort(key=lambda x: x[0])

        for idx, (_planned, notifs) in enumerate(items, 1):
            n0 = notifs[0]
            deadline = n0.deadline
            hw_name = deadline.hw_name or "Без названия"

            # Не показываем нумерацию если дедлайн один
            if total_deadlines == 1:
                lines.append(f"<b>{hw_name}</b>\n")
            else:
                lines.append(f"<b>{idx}. {hw_name}</b>\n")

            # Мягкий дедлайн (если есть и актуален)
            if deadline.soft_deadline_ts and deadline.soft_deadline_ts >= now:
                soft_str = format_deadline_datetime(deadline.soft_deadline_ts)
                remain = format_time_remaining(deadline.soft_deadline_ts, now)
                lines.append(f"🟡 {soft_str} {remain}\n")

            # Жёсткий дедлайн (если есть и актуален)
            if deadline.hard_deadline_ts and deadline.hard_deadline_ts >= now:
                hard_str = format_deadline_datetime(deadline.hard_deadline_ts)
                remain = format_time_remaining(deadline.hard_deadline_ts, now)
                lines.append(f"🔴 {hard_str} {remain}\n")

            lines.append("\n")

        return "".join(lines).strip()

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

            logger.info(f"(C) {chat_id} - Уведомление отправлено")
            return True

        except TelegramForbiddenError:
            logger.warning(f"(C) {chat_id} - Заблокирован")
            return False
        except TelegramBadRequest as e:
            logger.error(f"(C) {chat_id} - Ошибка: {e}")
            return False
        except Exception as e:
            logger.error(f"(C) {chat_id} - Ошибка: {e}")
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
        notification_ids = [n.id for n in notifications]
        if not notification_ids:
            return

        async with db_manager.async_session() as session:
            from sqlalchemy import update
            await session.execute(
                update(ChatScheduledNotification)
                .where(ChatScheduledNotification.id.in_(notification_ids))
                .values(status="sent", updated_at=datetime.now(UTC))
            )
            await session.commit()

    async def _mark_notifications_as_failed(self, notifications: list[ChatScheduledNotification]):
        """Отметить уведомления как неудачные"""
        notification_ids = [n.id for n in notifications]
        if not notification_ids:
            return

        async with db_manager.async_session() as session:
            from sqlalchemy import update
            await session.execute(
                update(ChatScheduledNotification)
                .where(ChatScheduledNotification.id.in_(notification_ids))
                .values(status="failed", updated_at=datetime.now(UTC))
            )
            await session.commit()


# Создаем экземпляр сервиса
chat_notification_sender = ChatNotificationSender()
