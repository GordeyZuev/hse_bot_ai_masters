from datetime import UTC, datetime, timedelta
from typing import Any

import pytz
from sqlalchemy import and_, or_, select

from src.core.database import db_manager
from src.core.models import Deadline, Subject, Subscription
from src.utils import get_logger


logger = get_logger()


class DeadlineService:
    """Сервис для работы с дедлайнами"""

    def __init__(self):
        pass

    async def get_user_deadlines(
        self, user_id: int, days: int = 15
    ) -> list[dict[str, Any]]:
        """Получить дедлайны пользователя на указанное количество дней"""
        async with db_manager.async_session() as session:
            try:
                # Вычисляем временной диапазон в UTC
                now = datetime.now(UTC)
                end_date = now + timedelta(days=days)

                # Дедлайны по подписанным предметам
                stmt = (
                    select(Deadline, Subject)
                    .join(Subject)
                    .join(Subscription)
                    .where(
                        and_(
                            Subscription.user_id == user_id,
                            or_(
                                and_(
                                    Deadline.soft_deadline_ts.isnot(None),
                                    Deadline.soft_deadline_ts >= now,
                                    Deadline.soft_deadline_ts <= end_date,
                                ),
                                and_(
                                    Deadline.hard_deadline_ts.isnot(None),
                                    Deadline.hard_deadline_ts >= now,
                                    Deadline.hard_deadline_ts <= end_date,
                                ),
                            ),
                        )
                    )
                )

                result = await session.execute(stmt)
                deadlines_data = []

                for deadline, subject in result.fetchall():
                    # Определяем ближайший актуальный дедлайн
                    nearest_deadline = None
                    deadline_type = None

                    # Проверяем, какие дедлайны еще актуальны (все в UTC)
                    soft_valid = (
                        deadline.soft_deadline_ts and deadline.soft_deadline_ts >= now
                    )
                    hard_valid = (
                        deadline.hard_deadline_ts and deadline.hard_deadline_ts >= now
                    )

                    if soft_valid and hard_valid:
                        # Оба дедлайна актуальны - выбираем ближайший
                        if deadline.soft_deadline_ts <= deadline.hard_deadline_ts:
                            nearest_deadline = deadline.soft_deadline_ts
                            deadline_type = "soft"
                        else:
                            nearest_deadline = deadline.hard_deadline_ts
                            deadline_type = "hard"
                    elif soft_valid:
                        # Только мягкий дедлайн актуален
                        nearest_deadline = deadline.soft_deadline_ts
                        deadline_type = "soft"
                    elif hard_valid:
                        # Только жесткий дедлайн актуален (мягкий уже прошел)
                        nearest_deadline = deadline.hard_deadline_ts
                        deadline_type = "hard"

                    if nearest_deadline:
                        # Вычисляем время до дедлайна (в UTC)
                        time_left = nearest_deadline - now
                        days_left = time_left.days
                        hours_left = time_left.seconds // 3600

                        deadlines_data.append(
                            {
                                "deadline": deadline,
                                "subject": subject,
                                "nearest_deadline": nearest_deadline,
                                "deadline_type": deadline_type,
                                "days_left": days_left,
                                "hours_left": hours_left,
                                "time_left": time_left,
                            }
                        )

                # Сортируем по времени ближайшего дедлайна (от ближайшего к дальнему)
                deadlines_data.sort(key=lambda x: x["nearest_deadline"])

                return deadlines_data

            except Exception as e:
                logger.error(f"Ошибка получения дедлайнов пользователя {user_id}: {e}")
                return []

    async def get_all_upcoming_deadlines(self, days: int = 7) -> list[dict[str, Any]]:
        """Получить все предстоящие дедлайны (для уведомлений)"""
        async with db_manager.async_session() as session:
            try:
                now = datetime.now(UTC)
                end_date = now + timedelta(days=days)

                stmt = (
                    select(Deadline, Subject)
                    .join(Subject)
                    .where(
                        or_(
                            and_(
                                Deadline.soft_deadline_ts.isnot(None),
                                Deadline.soft_deadline_ts >= now,
                                Deadline.soft_deadline_ts <= end_date,
                            ),
                            and_(
                                Deadline.hard_deadline_ts.isnot(None),
                                Deadline.hard_deadline_ts >= now,
                                Deadline.hard_deadline_ts <= end_date,
                            ),
                        )
                    )
                )

                result = await session.execute(stmt)
                deadlines_data = []

                for deadline, subject in result.fetchall():
                    # Определяем ближайший актуальный дедлайн для сортировки
                    now = datetime.now(UTC)
                    nearest_deadline = None

                    # Проверяем, какие дедлайны еще актуальны
                    soft_valid = (
                        deadline.soft_deadline_ts and deadline.soft_deadline_ts >= now
                    )
                    hard_valid = (
                        deadline.hard_deadline_ts and deadline.hard_deadline_ts >= now
                    )

                    if soft_valid and hard_valid:
                        # Оба дедлайна актуальны - выбираем ближайший
                        nearest_deadline = min(
                            deadline.soft_deadline_ts, deadline.hard_deadline_ts
                        )
                    elif soft_valid:
                        nearest_deadline = deadline.soft_deadline_ts
                    elif hard_valid:
                        nearest_deadline = deadline.hard_deadline_ts

                    if nearest_deadline:
                        deadlines_data.append(
                            {
                                "deadline": deadline,
                                "subject": subject,
                                "nearest_deadline": nearest_deadline,
                            }
                        )

                # Сортируем по времени ближайшего дедлайна
                deadlines_data.sort(key=lambda x: x["nearest_deadline"])

                return deadlines_data

            except Exception as e:
                logger.error(f"Ошибка получения всех дедлайнов: {e}")
                return []

    def format_deadline_message(
        self, deadline_data: dict[str, Any], user_tz_name: str = "Europe/Moscow"
    ) -> str:
        """Форматирование сообщения о дедлайне"""
        deadline = deadline_data["deadline"]
        subject = deadline_data["subject"]

        # Базовая информация
        message = f"📚 <b>{subject.name}</b>\n"
        message += f"📝 <b>{deadline.hw_name}</b>\n\n"

        # Текущее время (UTC) и TZ пользователя
        now = datetime.now(UTC)
        user_tz = pytz.timezone(user_tz_name)

        # Дедлайны с проверкой актуальности и правильным форматированием времени
        if deadline.soft_deadline_ts:
            soft_local = deadline.soft_deadline_ts.astimezone(user_tz)
            soft_date = soft_local.strftime("%d.%m.%Y %H:%M")

            if deadline.soft_deadline_ts >= now:
                message += f"🟡 <b>Мягкий дедлайн:</b> {soft_date}\n"
            else:
                message += f"🟡 <b>Мягкий дедлайн:</b> {soft_date} <i>(прошел)</i>\n"

        if deadline.hard_deadline_ts:
            hard_local = deadline.hard_deadline_ts.astimezone(user_tz)
            hard_date = hard_local.strftime("%d.%m.%Y %H:%M")

            if deadline.hard_deadline_ts >= now:
                message += f"🔴 <b>Жесткий дедлайн:</b> {hard_date}\n"
            else:
                message += f"🔴 <b>Жесткий дедлайн:</b> {hard_date} <i>(прошел)</i>\n"

        # Время до ближайшего актуального дедлайна
        if "nearest_deadline" in deadline_data:
            nearest = deadline_data["nearest_deadline"]
            deadline_type = deadline_data["deadline_type"]

            time_left = nearest - now
            days = time_left.days
            hours = time_left.seconds // 3600

            deadline_name = "мягкого" if deadline_type == "soft" else "жесткого"

            if days > 0:
                message += (
                    f"\n⏰ <b>До {deadline_name} дедлайна:</b> {days} дн. {hours} ч."
                )
            elif hours > 0:
                message += f"\n⏰ <b>До {deadline_name} дедлайна:</b> {hours} ч."
            else:
                message += f"\n🚨 <b>{deadline_name.capitalize()} дедлайн сегодня!</b>"

        # Ссылка на источник
        if deadline.source_link and deadline.source_link.strip():
            message += f"\n\n🔗 <a href='{deadline.source_link}'>Перейти к заданию</a>"

        # Комментарий
        if deadline.note and deadline.note.strip():
            message += f"\n\n💬 <i>{deadline.note}</i>"

        return message

    def format_deadlines_list(
        self,
        deadlines_data: list[dict[str, Any]],
        days: int,
        user_tz_name: str = "Europe/Moscow",
    ) -> str:
        """Форматирование списка дедлайнов"""
        if not deadlines_data:
            return f"📅 <b>Дедлайны на {days} дней</b>\n\nДедлайнов не найдено.\nВозможно, у вас нет подписок на предметы."

        message = f"📅 <b>Дедлайны на {days} дней</b>\n\n"

        user_tz = pytz.timezone(user_tz_name)
        for i, data in enumerate(deadlines_data, 1):
            deadline = data["deadline"]
            subject = data["subject"]

            message += f"<b>{i}. {subject.name}</b>\n"
            # Делаем название ДЗ гиперссылкой, если есть ссылка
            if deadline.source_link:
                message += (
                    f"📝 <a href='{deadline.source_link}'>{deadline.hw_name}</a>\n"
                )
            else:
                message += f"📝 {deadline.hw_name}\n"

            # Ближайший дедлайн с правильным цветом
            if data.get("nearest_deadline"):
                # Форматируем время в часовом поясе пользователя
                local_time = data["nearest_deadline"].astimezone(user_tz)
                date_str = local_time.strftime("%d.%m.%Y %H:%M")

                # Выбираем цвет в зависимости от типа дедлайна
                deadline_type_icon = "🟡" if data["deadline_type"] == "soft" else "🔴"
                message += f"{deadline_type_icon} {date_str}"

                # Время до дедлайна
                days_left = data.get("days_left", 0)
                hours_left = data.get("hours_left", 0)

                if days_left > 0:
                    message += f" ({days_left} дн.)"
                elif hours_left > 0:
                    message += f" ({hours_left} ч.)"
                else:
                    message += " (сегодня!)"

            message += "\n\n"

        message += f"<i>Всего дедлайнов: {len(deadlines_data)}</i>"
        return message


# Создаем экземпляр сервиса
deadline_service = DeadlineService()
