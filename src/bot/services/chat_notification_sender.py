import asyncio
from datetime import UTC, datetime, timedelta

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import and_, select
from sqlalchemy.orm import selectinload

from src.bot.services.chat_service import chat_service
from src.core.database import db_manager
from src.core.models import ChatScheduledNotification, ChatTopic, Task
from src.utils import get_logger, safe_send_message


logger = get_logger()


class ChatNotificationSender:
    """Сервис для отправки уведомлений в чаты"""

    def __init__(self):
        pass

    async def send_scheduled_chat_notifications(self, bot: Bot) -> dict[str, int]:
        """Отправить запланированные уведомления в чаты"""
        stats = {"sent": 0, "failed": 0, "skipped": 0, "total_processed": 0}

        try:
            logger.info("[SYSTEM] Проверка уведомлений для чатов")

            # Получаем уведомления для отправки (в течение ближайших 5 минут)
            notifications = await self._get_scheduled_notifications_for_delivery()

            if not notifications:
                logger.info("[SYSTEM] Нет уведомлений для чатов")
                return stats

            # Группируем уведомления по чатам и топикам
            chat_topic_notifications = self._group_notifications_by_chat_topic(notifications)
            logger.debug(
                f"Группировка уведомлений по чатам и топикам: chat_topics={len(chat_topic_notifications)}"
            )

            # Обрабатываем чаты и топики батчами
            batch_size = 5
            chat_topic_items = list(chat_topic_notifications.items())

            for i in range(0, len(chat_topic_items), batch_size):
                batch = chat_topic_items[i : i + batch_size]

                # Обрабатываем батч параллельно
                tasks = []
                for (chat_id, topic_id), topic_notifs in batch:
                    task = self._process_chat_notifications(
                        bot, chat_id, topic_id, topic_notifs, stats
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
            now = datetime.now(UTC)
            time_window = now + timedelta(minutes=5)

            logger.debug(f"Поиск уведомлений для чатов: now={now}, window={time_window}")

            stmt = (
                select(ChatScheduledNotification)
                .join(ChatTopic)
                .options(
                    selectinload(ChatScheduledNotification.chat_topic),
                    selectinload(ChatScheduledNotification.task)
                )
                .where(
                    and_(
                        ChatScheduledNotification.status == "scheduled",
                        ChatScheduledNotification.planned_delivery_time <= time_window,
                        ChatTopic.is_active,
                    )
                )
                .order_by(ChatScheduledNotification.planned_delivery_time)
            )

            result = await session.execute(stmt)
            notifications = list(result.scalars().all())
            logger.debug(f"Найдено {len(notifications)} активных уведомлений для чатов")
            return notifications

    def _group_notifications_by_chat_topic(
        self, notifications: list[ChatScheduledNotification]
    ) -> dict[tuple[int, int | None], list[ChatScheduledNotification]]:
        """Группировать уведомления по чатам и топикам"""
        grouped = {}
        for notification in notifications:
            chat_id = notification.chat_id
            topic_id = notification.topic_id
            key = (chat_id, topic_id)
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(notification)
        return grouped

    async def _process_chat_notifications(
        self,
        bot: Bot,
        chat_id: int,
        topic_id: int | None,
        notifications: list[ChatScheduledNotification],
        stats: dict[str, int]
    ):
        """Обработать уведомления для одного чата и топика"""
        batch_text = None
        message_thread_id = None

        try:
            # Проверяем, активен ли топик
            chat_topic = notifications[0].chat_topic
            if not chat_topic.is_active:
                stats["skipped"] += len(notifications)
                return

            # Группируем уведомления по задачам
            deadline_notifications = self._group_notifications_by_deadline(notifications)

            # Формируем единое сообщение (как в scheduled_notification_sender)
            batch_text = self._format_multiple_notifications(deadline_notifications)

            # Получаем topic_id для отправки в топик
            message_thread_id = chat_topic.topic_id

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
            # Проверяем, является ли это ошибкой миграции или отсутствия чата
            from aiogram.exceptions import TelegramBadRequest

            from src.bot.middlewares.private_chat import TelegramErrorHandler

            if isinstance(e, TelegramBadRequest):
                err_msg = str(e).lower()
                if "chat not found" in err_msg or "chat not exist" in err_msg:
                    logger.warning(f"(C) {chat_id} (topic: {topic_id}) - чат недоступен, деактивируем")
                    await chat_service.deactivate_chat(chat_id)
                    await self._mark_notifications_as_failed(list(notifications))
                    stats["failed"] += len(notifications)
                    stats["total_processed"] += len(notifications)
                    return

                # Пытаемся обработать миграцию
                new_chat_id = await TelegramErrorHandler.handle_chat_migration(e, chat_id, bot)
                if new_chat_id:
                    # Повторяем отправку с новым ID чата (если текст уже сформирован)
                    logger.info(f"(C) {chat_id} → {new_chat_id} - Чат мигрирован, повторная отправка")
                    try:
                        if batch_text and message_thread_id is not None:
                            sent_ok = await self._safe_send_batch(
                                bot, new_chat_id, batch_text, message_thread_id
                            )
                            if sent_ok:
                                stats["sent"] += len(notifications)
                                stats["total_processed"] += len(notifications)
                                await self._mark_notifications_as_sent(list(notifications))
                                return
                            else:
                                logger.error(f"(C) {new_chat_id} - Повторная отправка после миграции не удалась")
                    except Exception as retry_error:
                        logger.error(f"(C) {new_chat_id} - Ошибка повторной отправки после миграции: {retry_error}")

                    # Если повторная отправка не удалась — отмечаем как failed
                    await self._mark_notifications_as_failed(list(notifications))
                    stats["failed"] += len(notifications)
                    stats["total_processed"] += len(notifications)
                    return

            logger.error(f"(C) {chat_id} (topic: {topic_id}) - Ошибка обработки: {e}")
            await self._mark_notifications_as_failed(list(notifications))
            stats["failed"] += len(notifications)
            stats["total_processed"] += len(notifications)

    def _group_notifications_by_deadline(
        self, notifications: list[ChatScheduledNotification]
    ) -> dict[int, list[ChatScheduledNotification]]:
        """Группировать уведомления по задачам"""
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
        if not text.strip():
            return False
        return await safe_send_message(
            bot,
            chat_id=chat_id,
            text=text,
            success_message=f"(C) {chat_id} - Уведомление отправлено",
            is_group_chat=True,
            parse_mode="HTML",
            message_thread_id=message_thread_id,
            disable_web_page_preview=True,
        )

    def _format_multiple_notifications(
        self, deadline_notifications: dict[int, list[ChatScheduledNotification]]
    ) -> str:
        """Сформировать единое сообщение для нескольких дедлайнов."""
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
            if idx > 1:
                # Добавляем пустую строку между заданиями для лучшей читаемости
                lines.append("\n")
            n0 = notifs[0]
            deadline = n0.task
            hw_name = deadline.hw_name or "Без названия"

            # Не показываем нумерацию если дедлайн один
            if total_deadlines == 1:
                lines.append(f"<b>{hw_name}</b>\n")
            else:
                lines.append(f"<b>{idx}. {hw_name}</b>\n")

            has_any_deadline = False

            # Мягкий дедлайн (если есть и актуален)
            if deadline.soft_deadline_ts and deadline.soft_deadline_ts >= now:
                soft_str = format_deadline_datetime(deadline.soft_deadline_ts)
                remain = format_time_remaining(deadline.soft_deadline_ts, now)
                lines.append(f"🟡 {soft_str} {remain}\n")
                has_any_deadline = True

            # Жёсткий дедлайн (если есть и актуален)
            if deadline.hard_deadline_ts and deadline.hard_deadline_ts >= now:
                hard_str = format_deadline_datetime(deadline.hard_deadline_ts)
                remain = format_time_remaining(deadline.hard_deadline_ts, now)
                lines.append(f"🔴 {hard_str} {remain}\n")
                has_any_deadline = True

            # Если нет актуальных дедлайнов, но есть прошедшие - показываем их
            if not has_any_deadline:
                if deadline.soft_deadline_ts:
                    soft_str = format_deadline_datetime(deadline.soft_deadline_ts)
                    lines.append(f"🟡 {soft_str} <i>(прошёл)</i>\n")
                    has_any_deadline = True
                if deadline.hard_deadline_ts:
                    hard_str = format_deadline_datetime(deadline.hard_deadline_ts)
                    lines.append(f"🔴 {hard_str} <i>(прошёл)</i>\n")
                    has_any_deadline = True

            # Если вообще нет дедлайнов - показываем сообщение
            if not has_any_deadline:
                lines.append("<i>Дедлайны не указаны</i>\n")

            lines.append("\n")

        # Добавляем надпись в конце сообщения
        from src.bot.texts import CHAT_DEADLINE_FOOTER
        lines.append(CHAT_DEADLINE_FOOTER)

        return "".join(lines).strip()

    async def _send_chat_notification(
        self,
        bot: Bot,
        chat_id: int,
        notifications: list[ChatScheduledNotification]
    ) -> bool:
        """Отправить уведомление в чат"""
        if not notifications:
            return False

        # Формируем сообщение
        message_text = self._format_chat_notification_message(notifications)

        # Создаем клавиатуру
        keyboard = self._create_chat_notification_keyboard(notifications[0].task)

        # Получаем topic_id для отправки в топик
        chat_topic = notifications[0].chat_topic
        message_thread_id = chat_topic.topic_id

        # Отправляем сообщение
        return await safe_send_message(
            bot,
            chat_id=chat_id,
            text=message_text,
            success_message=f"(C) {chat_id} - Уведомление отправлено",
            is_group_chat=True,
            reply_markup=keyboard,
            parse_mode="HTML",
            message_thread_id=message_thread_id
        )

    def _format_chat_notification_message(
        self, notifications: list[ChatScheduledNotification]
    ) -> str:
        """Форматировать сообщение уведомления"""
        if not notifications:
            return ""

        deadline = notifications[0].task
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
        from src.utils.notification_formatting import format_deadline_datetime
        formatted_time = format_deadline_datetime(deadline_ts, "Europe/Moscow")
        text += f"{formatted_time}\n"

        if deadline.note:
            text += f"📄 <b>Примечание:</b> {deadline.note}\n"

        if deadline.source_link:
            text += f"🔗 <b>Ссылка:</b> {deadline.source_link}\n"

        # Добавляем надпись в конце сообщения
        from src.bot.texts import CHAT_DEADLINE_FOOTER
        text += CHAT_DEADLINE_FOOTER

        return text

    def _create_chat_notification_keyboard(self, deadline: Task) -> InlineKeyboardMarkup:
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
