from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select

from src.core.database import db_manager
from src.core.models import Subject, Subscription, Task, TaskUserStatus
from src.utils import get_logger
from src.utils.notification_formatting import (
    format_deadline_datetime,
    format_time_remaining,
)


logger = get_logger()


class DeadlineService:
    """Сервис для работы с дедлайнами"""

    def __init__(self):
        pass

    async def get_user_deadlines(
        self, user_id: int, days: int = 15, hide_done: bool = False
    ) -> list[dict[str, Any]]:
        """Получить дедлайны пользователя на указанное количество дней"""
        async with db_manager.async_session() as session:
            try:
                # Вычисляем временной диапазон в UTC
                now = datetime.now(UTC)
                end_date = now + timedelta(days=days)

                # Дедлайны по подписанным предметам
                tus = select(TaskUserStatus.deadline_id).where(TaskUserStatus.user_id == user_id).subquery()

                stmt = (
                    select(Task, Subject, tus.c.deadline_id)
                    .join(Subject)
                    .join(Subscription)
                    .outerjoin(tus, tus.c.deadline_id == Task.id)
                    .where(
                        and_(
                            Subscription.user_id == user_id,
                            or_(
                                and_(
                                    Task.soft_deadline_ts.isnot(None),
                                    Task.soft_deadline_ts >= now,
                                    Task.soft_deadline_ts <= end_date,
                                ),
                                and_(
                                    Task.hard_deadline_ts.isnot(None),
                                    Task.hard_deadline_ts >= now,
                                    Task.hard_deadline_ts <= end_date,
                                ),
                            ),
                        )
                    )
                )

                result = await session.execute(stmt)
                deadlines_data = []

                for deadline, subject, done_deadline_id in result.fetchall():
                    # Определяем ближайший актуальный дедлайн
                    nearest_deadline = None
                    deadline_type = None
                    is_done = done_deadline_id is not None

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

                        # Пропускаем выполненные, если включен фильтр
                        if hide_done and is_done:
                            continue

                        deadlines_data.append(
                            {
                                "deadline": deadline,
                                "subject": subject,
                                "nearest_deadline": nearest_deadline,
                                "deadline_type": deadline_type,
                                "days_left": days_left,
                                "hours_left": hours_left,
                                "time_left": time_left,
                                "is_done": is_done,
                            }
                        )

                # Сортируем: сначала невыполненные, затем по времени ближайшего дедлайна
                deadlines_data.sort(key=lambda x: (x.get("is_done", False), x["nearest_deadline"]))

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
                    select(Task, Subject)
                    .join(Subject)
                    .where(
                        or_(
                            and_(
                                Task.soft_deadline_ts.isnot(None),
                                Task.soft_deadline_ts >= now,
                                Task.soft_deadline_ts <= end_date,
                            ),
                            and_(
                                Task.hard_deadline_ts.isnot(None),
                                Task.hard_deadline_ts >= now,
                                Task.hard_deadline_ts <= end_date,
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

        # Текущее время (UTC)
        now = datetime.now(UTC)

        # Дедлайны с проверкой актуальности и правильным форматированием времени
        if deadline.soft_deadline_ts:
            soft_date = format_deadline_datetime(deadline.soft_deadline_ts, user_tz_name)

            if deadline.soft_deadline_ts >= now:
                message += f"🟡 <b>Мягкий дедлайн:</b> {soft_date}\n"
            else:
                message += f"🟡 <b>Мягкий дедлайн:</b> {soft_date} <i>(прошел)</i>\n"

        if deadline.hard_deadline_ts:
            hard_date = format_deadline_datetime(deadline.hard_deadline_ts, user_tz_name)

            if deadline.hard_deadline_ts >= now:
                message += f"🔴 <b>Жесткий дедлайн:</b> {hard_date}\n"
            else:
                message += f"🔴 <b>Жесткий дедлайн:</b> {hard_date} <i>(прошел)</i>\n"

        # Время до ближайшего актуального дедлайна
        if "nearest_deadline" in deadline_data:
            nearest = deadline_data["nearest_deadline"]
            deadline_type = deadline_data["deadline_type"]
            remain = format_time_remaining(nearest, now)
            deadline_name = "мягкого" if deadline_type == "soft" else "жесткого"
            icon = "🟡" if deadline_type == "soft" else "🔴"
            if remain == "(сегодня!)":
                message += f"\n{icon} <b>{deadline_name.capitalize()} дедлайн сегодня!</b>"
            else:
                message += f"\n{icon} <b>До {deadline_name} дедлайна:</b> {remain.strip('()')}"

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
                now = datetime.now(UTC)
                date_str = format_deadline_datetime(data["nearest_deadline"], user_tz_name)

                # Выбираем цвет в зависимости от типа дедлайна
                deadline_type_icon = "🟡" if data["deadline_type"] == "soft" else "🔴"
                remain = format_time_remaining(data["nearest_deadline"], now)
                message += f"{deadline_type_icon} {date_str} {remain}"

            message += "\n\n"

        message += f"<i>Всего дедлайнов: {len(deadlines_data)}</i>"
        return message


# Создаем экземпляр сервиса
deadline_service = DeadlineService()
