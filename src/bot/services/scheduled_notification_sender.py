import asyncio
from datetime import UTC, datetime, timedelta
from html import escape
from typing import Any

import pytz
from aiogram import Bot
from aiogram.enums import ButtonStyle
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from src.bot.services.rate_limiter import telegram_rate_limiter
from src.core.database import db_manager
from src.core.models import ScheduledNotification, Subject, Task
from src.utils import get_logger, safe_send_message
from src.utils.telegram_text import SAFE_MESSAGE_LENGTH, MessageTooLongError


logger = get_logger()


def _preview(value: str, limit: int) -> str:
    return value if len(value) <= limit else f"{value[: limit - 1]}…"


class ScheduledNotificationSender:
    """Сервис для отправки предрассчитанных уведомлений о дедлайнах"""

    def __init__(self):
        pass

    async def send_scheduled_notifications(self, bot: Bot) -> dict[str, int]:
        """Drain due notifications without limiting a whole cron run to 100 rows."""
        stats = {"sent": 0, "failed": 0, "skipped": 0, "total_processed": 0}

        try:
            logger.info("[SYSTEM] Проверка уведомлений")
            deadline = asyncio.get_running_loop().time() + 120
            while True:
                notifications = (
                    await db_manager.get_scheduled_notifications_for_delivery(
                        time_window_minutes=5
                    )
                )
                if not notifications:
                    break

                user_notifications = self._group_notifications_by_user(notifications)
                user_items = list(user_notifications.items())
                for i in range(0, len(user_items), 10):
                    batch = user_items[i : i + 10]
                    results = await asyncio.gather(
                        *(
                            self._process_user_notifications(
                                bot, user_id, user_notifs, stats
                            )
                            for user_id, user_notifs in batch
                        ),
                        return_exceptions=True,
                    )
                    for error in results:
                        if isinstance(error, BaseException):
                            logger.error(f"Ошибка обработки пачки напоминаний: {error}")
                if asyncio.get_running_loop().time() >= deadline:
                    logger.warning(
                        "[SYSTEM] Достигнут лимит времени отправки; остаток очереди "
                        "будет обработан следующим запуском"
                    )
                    break

            logger.info(
                "[SYSTEM] Напоминания: sent={} failed={} processed={}",
                stats["sent"],
                stats["failed"],
                stats["total_processed"],
            )

            return stats

        except Exception as e:
            logger.error(f"Ошибка отправки уведомлений: {e}")
            return stats

    def _group_notifications_by_user(
        self, notifications: list[ScheduledNotification]
    ) -> dict[int, list[ScheduledNotification]]:
        """Группировать уведомления по пользователям"""
        user_notifications = {}

        for notification in notifications:
            user_id = notification.user_id
            if user_id not in user_notifications:
                user_notifications[user_id] = []
            user_notifications[user_id].append(notification)

        return user_notifications

    async def _process_user_notifications(
        self,
        bot: Bot,
        user_id: int,
        user_notifs: list[ScheduledNotification],
        stats: dict[str, int],
    ):
        """Обработать уведомления для одного пользователя"""
        pending = [user_notifs]
        sent_messages = 0
        while pending:
            group = pending.pop(0)
            if sent_messages:
                await asyncio.sleep(1)  # Telegram's per-chat broadcast limit.
            try:
                success = await self._send_notifications_to_user(bot, user_id, group)
                sent_messages += 1
                if success:
                    stats["sent"] += len(group)
                    await db_manager.update_notification_statuses(
                        [notification.id for notification in group], "sent"
                    )
                else:
                    stats["failed"] += len(group)
                    await db_manager.update_notification_statuses(
                        [notification.id for notification in group],
                        "dead",
                        "Telegram rejected the message",
                    )
                stats["total_processed"] += len(group)
            except MessageTooLongError:
                if len(group) == 1:
                    logger.error(f"Уведомление {group[0].id} длиннее лимита Telegram")
                    stats["failed"] += 1
                    stats["total_processed"] += 1
                    await db_manager.update_notification_statuses(
                        [group[0].id], "dead", "Message exceeds Telegram limit"
                    )
                    continue
                middle = len(group) // 2
                pending[:0] = [group[:middle], group[middle:]]
            except TelegramRetryAfter as e:
                logger.warning(f"Telegram RetryAfter для {user_id}: {e.retry_after}с")
                stats["failed"] += len(group)
                stats["total_processed"] += len(group)
                await db_manager.update_notification_statuses(
                    [notification.id for notification in group],
                    "retry",
                    str(e),
                    retry_after_seconds=int(e.retry_after) + 1,
                )
            except Exception as e:
                logger.error(f"Ошибка отправки уведомлений пользователю {user_id}: {e}")
                stats["failed"] += len(group)
                stats["total_processed"] += len(group)
                dead_ids = [n.id for n in group if n.attempt_count >= 5]
                retry_ids = [n.id for n in group if n.attempt_count < 5]
                await db_manager.update_notification_statuses(dead_ids, "dead", str(e))
                await db_manager.update_notification_statuses(
                    retry_ids,
                    "retry",
                    str(e),
                    retry_after_seconds=min(
                        3600,
                        60 * 2 ** max(max(n.attempt_count for n in group) - 1, 0),
                    ),
                )

    async def _send_notifications_to_user(
        self, bot: Bot, user_id: int, notifications: list[ScheduledNotification]
    ) -> bool:
        """Отправить уведомления конкретному пользователю"""
        # Загружаем полную информацию о дедлайнах одним запросом
        notification_data = []

        # Собираем все ID дедлайнов для одного запроса
        deadline_ids = [notification.deadline_id for notification in notifications]

        async with db_manager.async_session() as session:
            stmt = select(Task, Subject).join(Subject).where(Task.id.in_(deadline_ids))
            result = await session.execute(stmt)
            deadline_subjects = result.all()

            # Создаем словарь для быстрого поиска
            deadline_dict = {
                deadline.id: (deadline, subject)
                for deadline, subject in deadline_subjects
            }

            for notification in notifications:
                if notification.deadline_id in deadline_dict:
                    deadline, subject = deadline_dict[notification.deadline_id]
                    notification_data.append(
                        {
                            "notification": notification,
                            "deadline": deadline,
                            "subject": subject,
                        }
                    )

        if not notification_data:
            logger.warning(
                f"Не найдены дедлайны для уведомлений пользователя {user_id}"
            )
            return False

        # Определяем TZ пользователя для форматирования
        user = await db_manager.get_user_by_id(user_id)
        user_tz = (
            pytz.timezone(user.timezone)
            if user and user.timezone
            else pytz.timezone("Europe/Moscow")
        )

        # Получаем настройки уведомлений для проверки времени сна
        from src.bot.services.notification_service import notification_service

        await notification_service.get_user_notification_settings(user_id)

        message = await self._format_notifications_message(notification_data, user_tz)

        # Проверяем задержку по UTC
        now_utc = datetime.now(UTC)
        planned_times = [
            d["notification"].planned_delivery_time for d in notification_data
        ]
        delay_threshold = now_utc - timedelta(minutes=30)
        is_delayed = any(pt and pt < delay_threshold for pt in planned_times)

        if is_delayed:
            message = "⚠️ <i>Отправлено с задержкой (>30 мин)</i>\n\n" + message

        if len(message) > SAFE_MESSAGE_LENGTH:
            raise MessageTooLongError("Notification text exceeds safe Telegram limit")

        # Клавиатура для быстрого перехода к дедлайнам
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📅 Дедлайны",
                        callback_data="quick_deadlines",
                        style=ButtonStyle.PRIMARY,
                    )
                ]
            ]
        )

        # Отправляем сообщение
        await telegram_rate_limiter.acquire()
        return await safe_send_message(
            bot,
            chat_id=user_id,
            text=message,
            user_id=user_id,
            success_message=f"(U) {user_id} - Отправлено {len(notifications)} уведомлений",
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=keyboard,
        )

    async def _format_notifications_message(
        self, notification_data: list[dict[str, Any]], user_tz
    ) -> str:
        """Форматировать сообщение с уведомлениями"""
        if len(notification_data) == 1:
            return self._format_single_notification(notification_data[0], user_tz)
        else:
            return self._format_multiple_notifications(notification_data, user_tz)

    def _format_single_notification(self, data: dict[str, Any], user_tz) -> str:
        """Форматировать одиночное уведомление"""
        notification = data["notification"]
        deadline = data["deadline"]
        subject = data["subject"]

        deadline_type_icon = "🟡" if notification.deadline_type == "soft" else "🔴"

        if notification.deadline_type == "soft":
            deadline_ts = deadline.soft_deadline_ts
        else:
            deadline_ts = deadline.hard_deadline_ts

        from src.utils.notification_formatting import (
            format_deadline_tg_time,
            format_time_remaining,
        )

        now = datetime.now(UTC)
        deadline_str = format_deadline_tg_time(deadline_ts, tz_name=user_tz.zone)
        time_left_str = format_time_remaining(deadline_ts, now).strip("()")

        message = "⏰ <b>Напоминание о дедлайне</b>\n\n"
        message += f"📚 <b>Предмет:</b> {escape(_preview(subject.name, 120))}\n"

        if deadline.hw_name:
            task_name = escape(_preview(deadline.hw_name, 160))
            if deadline.source_link and len(deadline.source_link) <= 1024:
                message += (
                    f"📝 <b>Задание:</b> <a href='{escape(deadline.source_link, quote=True)}'>"
                    f"{task_name}</a>\n"
                )
            else:
                message += f"📝 <b>Задание:</b> {task_name}\n"

        message += f"{deadline_type_icon} <b>Дедлайн:</b> {deadline_str} (Осталось {time_left_str})\n"

        if deadline.note:
            message += f"\n💬 <i>{escape(_preview(deadline.note, 900))}</i>"

        return message

    def _format_multiple_notifications(
        self, notification_data: list[dict[str, Any]], user_tz
    ) -> str:
        """Форматировать множественные уведомления"""
        message = f"⏰ <b>Напоминания о дедлайнах ({len(notification_data)})</b>\n\n"

        # Сортируем по времени дедлайна
        notification_data.sort(key=lambda x: x["notification"].original_deadline_ts)

        for i, data in enumerate(notification_data, 1):
            notification = data["notification"]
            deadline = data["deadline"]
            subject = data["subject"]

            deadline_type_icon = "🟡" if notification.deadline_type == "soft" else "🔴"

            if notification.deadline_type == "soft":
                deadline_ts = deadline.soft_deadline_ts
            else:
                deadline_ts = deadline.hard_deadline_ts

            from src.utils.notification_formatting import (
                format_deadline_tg_time,
                format_time_remaining,
            )

            now = datetime.now(UTC)

            deadline_str = format_deadline_tg_time(deadline_ts, tz_name=user_tz.zone)
            time_left_str = format_time_remaining(deadline_ts, now).strip("()")

            if i > 1:
                message += "\n"

            message += f"<b>{i}. {escape(_preview(subject.name, 120))}</b>\n"

            if deadline.hw_name:
                task_name = escape(_preview(deadline.hw_name, 160))
                if deadline.source_link and len(deadline.source_link) <= 1024:
                    message += (
                        f"• 📝 <a href='{escape(deadline.source_link, quote=True)}'>"
                        f"{task_name}</a>\n"
                    )
                else:
                    message += f"• 📝 {task_name}\n"

            message += f"• {deadline_type_icon} <b>Дедлайн:</b> {deadline_str} (Осталось {time_left_str})\n"

        return message


# Создаем экземпляр сервиса
scheduled_notification_sender = ScheduledNotificationSender()
