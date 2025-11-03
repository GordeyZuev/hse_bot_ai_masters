import asyncio
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.types import FSInputFile
from sqlalchemy import case, func, select

from src.bot.services.subscription_service import subscription_service
from src.core.database import db_manager
from src.core.models import (
    ChatGroup,
    ChatScheduledNotification,
    Deadline,
    ScheduledNotification,
    User,
)
from src.utils import get_logger, get_week_monday, safe_send_message


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

                week_ago = datetime.now(UTC) - timedelta(days=7)
                month_ago = datetime.now(UTC) - timedelta(days=30)

                stmt = select(
                    func.count(User.tg_user_id).label("total_users"),
                    func.count(
                        case((User.last_activity_ts >= week_ago, 1), else_=None)
                    ).label("active_week"),
                    func.count(
                        case((User.last_activity_ts >= month_ago, 1), else_=None)
                    ).label("active_month"),
                )
                result = await session.execute(stmt)
                row = result.first()

                stats["total_users"] = row.total_users or 0
                stats["active_users_week"] = row.active_week or 0
                stats["active_users_month"] = row.active_month or 0

                subscription_stats = await subscription_service.get_subscription_stats()
                stats.update(subscription_stats)

                stmt = select(func.count(Deadline.id))
                result = await session.execute(stmt)
                stats["total_deadlines"] = result.scalar() or 0

                now = datetime.now(UTC)
                stmt = select(func.count(Deadline.id)).where(
                    (Deadline.soft_deadline_ts >= now)
                    | (Deadline.hard_deadline_ts >= now)
                )
                result = await session.execute(stmt)
                stats["active_deadlines"] = result.scalar() or 0

                stmt = select(func.count(ScheduledNotification.id)).where(
                    ScheduledNotification.status == "scheduled"
                )
                result = await session.execute(stmt)
                stats["scheduled_notifications"] = result.scalar() or 0

                # Запланированные уведомления для чатов
                stmt = select(func.count(ChatScheduledNotification.id)).where(
                    ChatScheduledNotification.status == "scheduled"
                )
                result = await session.execute(stmt)
                stats["scheduled_chat_notifications"] = result.scalar() or 0

                # Статистика по групповым чатам (только активные)
                stmt = select(func.count(ChatGroup.chat_id)).where(ChatGroup.is_active)
                result = await session.execute(stmt)
                stats["total_chats"] = result.scalar() or 0

                stmt = select(func.max(Deadline.last_updated))
                result = await session.execute(stmt)
                last_sync_dt = result.scalar()
                if last_sync_dt:
                    stats["last_sync"] = last_sync_dt.astimezone(UTC).strftime(
                        "%H:%M:%S %d.%m.%y UTC"
                    )
                else:
                    stats["last_sync"] = "Нет данных"

                return stats

            except Exception as e:
                logger.error(f"Ошибка получения статистики: {e}")
                return {}

    async def get_users_count(self) -> int:
        """Получить количество пользователей для рассылки"""
        async with db_manager.async_session() as session:
            try:
                stmt = select(func.count(User.tg_user_id))
                result = await session.execute(stmt)
                return result.scalar() or 0

            except Exception as e:
                logger.error(f"Ошибка получения количества пользователей: {e}")
                return 0

    async def get_users_for_broadcast(self) -> list[User]:
        """Получить список пользователей для рассылки"""
        async with db_manager.async_session() as session:
            try:
                stmt = select(User)

                result = await session.execute(stmt)
                return list(result.scalars().all())

            except Exception as e:
                logger.error(f"Ошибка получения пользователей для рассылки: {e}")
                return []

    async def send_broadcast(
        self,
        message_text: str,
        bot: Bot,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> dict[str, int]:
        """Отправить массовую рассылку"""
        try:
            users = await self.get_users_for_broadcast()
            total_users = len(users)

            if total_users == 0:
                return {"success": 0, "errors": 0}

            success_count = 0
            error_count = 0

            logger.info(f"Рассылка для {total_users} пользователей")

            for i, user in enumerate(users, 1):
                success = await safe_send_message(
                    bot,
                    chat_id=user.tg_user_id,
                    text=message_text,
                    user_id=user.tg_user_id,
                    parse_mode="HTML"
                )

                if success:
                    success_count += 1
                else:
                    error_count += 1

                # Задержка между отправками (30 сообщений в секунду - лимит Telegram)
                if i % 30 == 0:
                    await asyncio.sleep(1)

                if progress_callback and i % 10 == 0:
                    progress_callback(i, total_users)

            logger.info(
                f"Рассылка завершена: {success_count} успешно, {error_count} ошибок"
            )

            return {"success": success_count, "errors": error_count}

        except Exception as e:
            logger.error(f"Ошибка выполнения рассылки: {e}")
            return {"success": 0, "errors": 0}

    async def get_current_log_files(self) -> list[tuple]:
        """Получить пути к текущим файлам логов (недельные и месячные)"""
        try:
            log_files = []
            log_dir = Path("logs")

            if not log_dir.exists():
                return []

            # Для логов с недельной ротацией используем дату понедельника текущей недели
            week_date_str = get_week_monday()

            app_log_path = log_dir / f"app_week_{week_date_str}.log"
            if app_log_path.exists():
                log_files.append(("app", str(app_log_path)))

            current_month = datetime.now(UTC).strftime("%Y-%m")
            error_log_path = log_dir / f"errors_{current_month}.log"
            if error_log_path.exists():
                log_files.append(("error", str(error_log_path)))

            return log_files

        except Exception as e:
            logger.error(f"Ошибка поиска файлов логов: {e}")
            return []

    async def send_logs_to_admin(self, bot: Bot, admin_id: int) -> bool:
        """Отправить текущие файлы логов администратору"""
        try:
            log_files = await self.get_current_log_files()

            if not log_files:
                await bot.send_message(
                    admin_id, "📄 <b>Текущие логи</b>\n\n❌ Файлы логов не найдены"
                )
                return False

            for log_type, file_path in log_files:
                try:
                    if not os.path.exists(file_path):
                        logger.warning(f"Файл {file_path} не существует")
                        continue

                    file_size = os.path.getsize(file_path)
                    if file_size == 0:
                        logger.warning(f"Файл {file_path} пустой, пропускаем отправку")
                        await bot.send_message(
                            admin_id,
                            f"📄 <b>Файл {log_type} логов</b>\n\n⚠️ Файл пустой",
                        )
                        continue

                    # Получаем имя файла из пути
                    filename = os.path.basename(file_path)

                    if log_type == "app":
                        caption = "📄 <b>Основные логи (недельная ротация)</b>"
                    elif log_type == "json":
                        caption = "📊 <b>JSON логи (недельная ротация)</b>"
                    else:  # error
                        caption = "🚨 <b>Логи ошибок (месячная ротация)</b>"

                    document = FSInputFile(file_path, filename=filename)

                    await bot.send_document(admin_id, document, caption=caption)

                    logger.info(f"Отправлен файл логов {log_type}: {file_path}")

                except Exception as e:
                    logger.error(f"Ошибка отправки файла {log_type}: {e}")
                    await bot.send_message(
                        admin_id, f"❌ Ошибка отправки файла {log_type}: {e!s}"
                    )

            logger.info(f"(A) {admin_id} - Логи отправлены")
            return True

        except Exception as e:
            logger.error(f"Ошибка отправки логов: {e}")
            await bot.send_message(
                admin_id,
                f"📄 <b>Текущие логи</b>\n\n❌ Ошибка при отправке логов: {e!s}",
            )
            return False

admin_service = AdminService()
