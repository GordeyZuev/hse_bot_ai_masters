import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import FSInputFile
from sqlalchemy import case, func, select

from src.bot.middlewares.private_chat import TelegramErrorHandler
from src.bot.services.event_export import iter_event_export
from src.bot.services.log_export import iter_log_export
from src.bot.services.rate_limiter import telegram_rate_limiter
from src.bot.services.subscription_service import subscription_service
from src.core.database import db_manager
from src.core.models import (
    ChatScheduledNotification,
    ScheduledNotification,
    Subject,
    Subscription,
    Task,
    User,
)
from src.utils import get_logger


logger = get_logger()


class AdminService:
    """Сервис для административных функций"""

    def __init__(self):
        pass

    async def get_bot_statistics(self) -> dict[str, Any]:
        """Получить основную статистику бота"""
        async with db_manager.async_session() as session:
            try:
                stats = {}

                now = datetime.now(UTC)
                day_ago = now - timedelta(days=1)
                week_ago = now - timedelta(days=7)
                month_ago = datetime.now(UTC) - timedelta(days=30)

                user_stats_stmt = select(
                    func.count(User.tg_user_id).label("total_users"),
                    func.count(
                        case((User.last_activity >= day_ago, 1), else_=None)
                    ).label("active_day"),
                    func.count(
                        case((User.last_activity >= week_ago, 1), else_=None)
                    ).label("active_week"),
                    func.count(
                        case((User.last_activity >= month_ago, 1), else_=None)
                    ).label("active_month"),
                )
                user_result = await session.execute(user_stats_stmt)
                user_row = user_result.first()

                stats["total_users"] = user_row.total_users or 0
                stats["active_users_day"] = user_row.active_day or 0
                stats["active_users_week"] = user_row.active_week or 0
                stats["active_users_month"] = user_row.active_month or 0

                subscription_stats = await subscription_service.get_subscription_stats()
                stats.update(subscription_stats)

                deadline_stats_stmt = select(
                    func.count(Task.id)
                    .filter(Task.is_archived.is_(False))
                    .label("total_deadlines"),
                    func.count(
                        case(
                            (
                                (
                                    (Task.soft_deadline_ts >= now)
                                    | (Task.hard_deadline_ts >= now)
                                )
                                & Task.is_archived.is_(False),
                                1,
                            ),
                            else_=None,
                        )
                    ).label("active_deadlines"),
                    func.max(Task.updated_at).label("last_sync"),
                )
                deadline_result = await session.execute(deadline_stats_stmt)
                deadline_row = deadline_result.first()

                stats["total_deadlines"] = deadline_row.total_deadlines or 0
                stats["active_deadlines"] = deadline_row.active_deadlines or 0

                last_sync_dt = deadline_row.last_sync
                if last_sync_dt:
                    stats["last_sync"] = last_sync_dt.astimezone(UTC).strftime(
                        "%H:%M:%S %d.%m.%y UTC"
                    )
                else:
                    stats["last_sync"] = "Нет данных"

                scheduled_result = await session.execute(
                    select(func.count(ScheduledNotification.id)).where(
                        ScheduledNotification.status == "scheduled"
                    )
                )
                stats["scheduled_notifications"] = scheduled_result.scalar() or 0

                chat_scheduled_result = await session.execute(
                    select(func.count(ChatScheduledNotification.id)).where(
                        ChatScheduledNotification.status == "scheduled"
                    )
                )
                stats["scheduled_chat_notifications"] = (
                    chat_scheduled_result.scalar() or 0
                )

                # Статистика по групповым чатам (только активные топики)
                from src.core.models.models import ChatTopic

                chat_result = await session.execute(
                    select(func.count(ChatTopic.id)).where(ChatTopic.is_active)
                )
                stats["total_chats"] = chat_result.scalar() or 0

                return stats

            except Exception as e:
                logger.error(f"Ошибка получения статистики: {e}")
                return {}

    async def get_users_count(self) -> int:
        """Получить количество пользователей для рассылки"""
        async with db_manager.async_session() as session:
            try:
                stmt = select(func.count(User.tg_user_id)).where(User.is_active)
                result = await session.execute(stmt)
                return result.scalar() or 0

            except Exception as e:
                logger.error(f"Ошибка получения количества пользователей: {e}")
                return 0

    async def get_users_for_broadcast(self) -> list[User]:
        """Получить список пользователей для рассылки"""
        async with db_manager.async_session() as session:
            try:
                stmt = select(User).where(User.is_active).order_by(User.tg_user_id)

                result = await session.execute(stmt)
                return list(result.scalars().all())

            except Exception as e:
                logger.error(f"Ошибка получения пользователей для рассылки: {e}")
                return []

    async def send_broadcast(
        self,
        bot: Bot,
        source_chat_id: int,
        source_message_id: int,
        progress_callback: Callable[[int, int], None | Awaitable[None]] | None = None,
    ) -> dict[str, int | float]:
        """Отправить массовую рассылку"""
        start_time = time.time()
        users = await self.get_users_for_broadcast()
        success_count = error_count = 0
        for index, user in enumerate(users, 1):
            sent = False
            for attempt in range(2):
                try:
                    await telegram_rate_limiter.acquire()
                    await bot.copy_message(
                        chat_id=user.tg_user_id,
                        from_chat_id=source_chat_id,
                        message_id=source_message_id,
                    )
                    sent = True
                    break
                except TelegramRetryAfter as exc:
                    if attempt == 0:
                        await asyncio.sleep(exc.retry_after + 1)
                        continue
                    logger.warning(
                        f"Рассылка: повторный flood control для {user.tg_user_id}"
                    )
                except TelegramForbiddenError:
                    await TelegramErrorHandler.deactivate_user(user.tg_user_id)
                    break
                except TelegramBadRequest as exc:
                    logger.warning(
                        f"Рассылка: ошибка Telegram для {user.tg_user_id}: {exc}"
                    )
                    break
                except Exception as exc:
                    logger.error(f"Рассылка: ошибка для {user.tg_user_id}: {exc}")
                    break
            if sent:
                success_count += 1
            else:
                error_count += 1
            if progress_callback and index % 10 == 0:
                progress = progress_callback(index, len(users))
                if asyncio.iscoroutine(progress):
                    await progress

        duration = time.time() - start_time
        logger.info(f"Рассылка: {success_count}/{len(users)} за {duration:.1f} с")
        return {"success": success_count, "errors": error_count, "duration": duration}

    async def send_logs_to_admin(
        self,
        bot: Bot,
        admin_id: int,
        start: date | None = None,
        end: date | None = None,
    ) -> bool:
        """Send complete logs for a short date range in bounded ZIP parts."""
        try:
            start = start or datetime.now().date()
            end = end or start
            with TemporaryDirectory(prefix="hse-bot-logs-") as temp_dir:
                parts = iter_log_export(
                    Path(os.getenv("LOG_DIR", "logs")),
                    Path(temp_dir),
                    start,
                    end,
                )
                number = 0
                while part := await asyncio.to_thread(next, parts, None):
                    number += 1
                    await bot.send_document(
                        admin_id,
                        FSInputFile(
                            part,
                            filename=f"hse-bot-logs-{start}-{end}-{number:03d}.zip",
                        ),
                        caption=f"📄 Логи {start}—{end}, часть {number}",
                    )
                    part.unlink()
                    if number:
                        await asyncio.sleep(1)
                return number > 0
        except Exception:
            logger.exception(f"(A) {admin_id} - Не удалось отправить логи")
            return False

    async def send_events_to_admin(
        self, bot: Bot, admin_id: int, start: date, end: date
    ) -> bool:
        """Send every stored product event for the requested UTC dates."""
        try:
            with TemporaryDirectory(prefix="hse-bot-events-") as temp_dir:
                number = 0
                async for part in iter_event_export(Path(temp_dir), start, end):
                    number += 1
                    await bot.send_document(
                        admin_id,
                        FSInputFile(
                            part,
                            filename=f"hse-bot-events-{start}-{end}-{number:03d}.zip",
                        ),
                        caption=f"📊 События UTC {start}—{end}, часть {number}",
                    )
                    part.unlink()
                    await asyncio.sleep(1)
                return number > 0
        except Exception:
            logger.exception(f"(A) {admin_id} - Не удалось отправить события")
            return False

    async def get_user_info_by_identifier(
        self, identifier: str
    ) -> dict[str, Any] | None:
        """Получить информацию о пользователе по ID или username

        Args:
            identifier: ID пользователя (число) или username (с @ или без)

        Returns:
            Словарь с информацией о пользователе или None если не найден
        """
        async with db_manager.async_session() as session:
            try:
                # Убираем @ если есть
                clean_identifier = identifier.lstrip("@")

                # Определяем тип идентификатора и ищем пользователя
                if clean_identifier.isdigit():
                    stmt = select(User).where(User.tg_user_id == int(clean_identifier))
                else:
                    stmt = select(User).where(User.username == clean_identifier)

                result = await session.execute(stmt)
                user = result.scalar_one_or_none()

                if not user:
                    return None

                # Получаем подписки пользователя
                subscriptions_stmt = (
                    select(Subject)
                    .join(Subscription)
                    .where(Subscription.user_id == user.tg_user_id)
                    .order_by(Subject.name)
                )
                subscriptions_result = await session.execute(subscriptions_stmt)
                subscriptions = list(subscriptions_result.scalars().all())

                return {
                    "user": user,
                    "subscriptions": subscriptions,
                }

            except Exception as e:
                logger.error(
                    f"Ошибка получения информации о пользователе {identifier}: {e}"
                )
                return None


admin_service = AdminService()
