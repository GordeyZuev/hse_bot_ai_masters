from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, select

from src.core.database import db_manager
from src.core.models import (
    ScheduledNotification,
    Subject,
    Subscription,
    Task,
    TaskUserStatus,
    User,
    UserNotificationSettings,
)
from src.utils import get_logger
from src.utils.time import utc_now


logger = get_logger()


class NotificationSchedulerService:
    """Сервис для планирования уведомлений о дедлайнах"""

    async def _get_user_tasks(self, user_id: int) -> list[Task]:
        """Получить все активные дедлайны пользователя"""
        async with db_manager.async_session() as session:
            tus = (
                select(TaskUserStatus.deadline_id)
                .where(TaskUserStatus.user_id == user_id)
                .subquery()
            )

            stmt = (
                select(Task)
                .join(Subject)
                .join(Subscription)
                .outerjoin(tus, tus.c.deadline_id == Task.id)
                .where(
                    and_(
                        Subscription.user_id == user_id,
                        Subject.is_active,
                        tus.c.deadline_id.is_(None),
                    )
                )
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def _get_subject_tasks(self, subject_id: int) -> list[Task]:
        """Получить все активные дедлайны по предмету"""
        async with db_manager.async_session() as session:
            stmt = select(Task).where(Task.subject_id == subject_id)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def _get_user_and_settings(
        self, user_id: int
    ) -> tuple[User, UserNotificationSettings]:
        """Получить пользователя и его настройки уведомлений одним запросом"""
        async with db_manager.async_session() as session:
            try:
                stmt = (
                    select(User, UserNotificationSettings)
                    .join(
                        UserNotificationSettings,
                        User.tg_user_id == UserNotificationSettings.user_id,
                    )
                    .where(User.tg_user_id == user_id)
                )

                result = await session.execute(stmt)
                row = result.first()

                if not row:
                    error_msg = f"Пользователь {user_id} не найден"
                    logger.error(error_msg)
                    raise ValueError(error_msg)

                user, settings = row

                if not settings.is_active:
                    error_msg = f"Уведомления отключены для пользователя {user_id}"
                    logger.debug(error_msg)
                    raise ValueError(error_msg)

                return user, settings

            except ValueError:
                raise
            except Exception as e:
                logger.error(f"Ошибка получения пользователя и настроек {user_id}: {e}")
                raise

    async def _schedule_notifications_for_tasks(
        self, user: User, deadlines: list[Task], settings: UserNotificationSettings
    ) -> int:
        """Планировать уведомления для списка дедлайнов"""
        total_scheduled = 0

        for deadline in deadlines:
            if deadline.soft_deadline_ts:
                count = await self._schedule_notifications_for_user_task(
                    user, deadline, "soft", deadline.soft_deadline_ts, settings
                )
                total_scheduled += count

            if deadline.hard_deadline_ts:
                count = await self._schedule_notifications_for_user_task(
                    user, deadline, "hard", deadline.hard_deadline_ts, settings
                )
                total_scheduled += count

        return total_scheduled

    async def _cancel_notifications_for_tasks(
        self, user_id: int, deadlines: list[Task]
    ) -> int:
        """Отменить уведомления пользователя для списка дедлайнов"""
        total_cancelled = 0

        for deadline in deadlines:
            async with db_manager.async_session() as session:
                cancel_stmt = select(ScheduledNotification).where(
                    and_(
                        ScheduledNotification.user_id == user_id,
                        ScheduledNotification.deadline_id == deadline.id,
                        ScheduledNotification.status == "scheduled",
                    )
                )
                result = await session.execute(cancel_stmt)
                notifications_to_cancel = result.scalars().all()

                for notification in notifications_to_cancel:
                    notification.status = "cancelled"
                    notification.updated_at = utc_now()
                    total_cancelled += 1

                await session.commit()

        return total_cancelled

    async def schedule_notifications_for_task(self, deadline: Task) -> int:
        """Создать запланированные уведомления для дедлайна"""
        try:
            # Существующая логика для пользователей
            subscribed_users = await self._get_subscribed_users(deadline.subject_id)

            user_notifications_scheduled = 0
            if subscribed_users:
                for user in subscribed_users:
                    settings = await db_manager.get_user_notification_settings(
                        user.tg_user_id
                    )

                    if not settings.is_active:
                        continue

                    if deadline.soft_deadline_ts:
                        soft_count = await self._schedule_notifications_for_user_task(
                            user, deadline, "soft", deadline.soft_deadline_ts, settings
                        )
                        user_notifications_scheduled += soft_count

                    if deadline.hard_deadline_ts:
                        hard_count = await self._schedule_notifications_for_user_task(
                            user, deadline, "hard", deadline.hard_deadline_ts, settings
                        )
                        user_notifications_scheduled += hard_count

            # Новая логика для чатов
            from src.bot.services.chat_notification_scheduler_service import (
                chat_notification_scheduler_service,
            )
            chat_notifications_scheduled = await chat_notification_scheduler_service.schedule_notifications_for_task(deadline)

            total_scheduled = user_notifications_scheduled + chat_notifications_scheduled

            logger.info(
                f"Запланировано {total_scheduled} уведомлений для дедлайна {deadline.id} "
                f"(пользователи: {user_notifications_scheduled}, чаты: {chat_notifications_scheduled})"
            )
            return total_scheduled

        except Exception as e:
            logger.error(
                f"Ошибка планирования уведомлений для дедлайна {deadline.id}: {e}"
            )
            return 0

    async def _get_subscribed_users(self, subject_id: int) -> list[User]:
        """Получить пользователей, подписанных на предмет"""
        async with db_manager.async_session() as session:
            try:
                stmt = (
                    select(User)
                    .join(Subscription)
                    .where(Subscription.subject_id == subject_id)
                )
                result = await session.execute(stmt)
                return list(result.scalars().all())

            except Exception as e:
                logger.error(f"Ошибка получения подписчиков предмета {subject_id}: {e}")
                return []

    async def _schedule_notifications_for_user_task(
        self,
        user: User,
        deadline: Task,
        deadline_type: str,
        deadline_ts: datetime,
        settings: UserNotificationSettings,
    ) -> int:
        """Создать уведомления для пользователя и конкретного дедлайна"""
        try:
            scheduled_count = 0

            reminder1_time = self._calculate_notification_time(
                deadline_ts, settings.reminder1_offset, settings.reminder1_unit
            )

            if reminder1_time and reminder1_time > datetime.now(UTC):
                await self._create_scheduled_notification(
                    user.tg_user_id,
                    deadline.id,
                    deadline_type,
                    1,
                    deadline_ts,
                    reminder1_time,
                )
                scheduled_count += 1

            reminder2_time = self._calculate_notification_time(
                deadline_ts, settings.reminder2_offset, settings.reminder2_unit
            )

            if reminder2_time and reminder2_time > datetime.now(UTC):
                await self._create_scheduled_notification(
                    user.tg_user_id,
                    deadline.id,
                    deadline_type,
                    2,
                    deadline_ts,
                    reminder2_time,
                )
                scheduled_count += 1

            return scheduled_count

        except Exception as e:
            logger.error(
                f"Ошибка планирования уведомлений для пользователя {user.tg_user_id}: {e}"
            )
            return 0

    def _calculate_notification_time(
        self, deadline_ts: datetime, offset: int, unit: str
    ) -> datetime | None:
        """Вычислить время отправки уведомления"""
        try:
            if unit == "days":
                delta = timedelta(days=offset)
            elif unit == "hours":
                delta = timedelta(hours=offset)
            else:
                logger.warning(f"Неизвестная единица времени: {unit}")
                return None

            notification_time = deadline_ts - delta

            if notification_time <= datetime.now(UTC):
                return None

            return notification_time

        except Exception as e:
            logger.error(f"Ошибка вычисления времени уведомления: {e}")
            return None

    async def _create_scheduled_notification(
        self,
        user_id: int,
        deadline_id: int,
        deadline_type: str,
        notification_number: int,
        original_deadline_ts: datetime,
        planned_delivery_time: datetime,
    ) -> bool:
        """Создать запись запланированного уведомления"""
        try:
            async with db_manager.async_session() as session:
                existing_stmt = select(ScheduledNotification).where(
                    and_(
                        ScheduledNotification.user_id == user_id,
                        ScheduledNotification.deadline_id == deadline_id,
                        ScheduledNotification.deadline_type == deadline_type,
                        ScheduledNotification.notification_number
                        == notification_number,
                    )
                )
                result = await session.execute(existing_stmt)
                existing = result.scalar_one_or_none()

                if existing:
                    existing.original_deadline_ts = original_deadline_ts
                    existing.planned_delivery_time = planned_delivery_time
                    existing.status = "scheduled"
                    existing.updated_at = utc_now()
                    await session.commit()
                    return True

            notification_data = {
                "user_id": user_id,
                "deadline_id": deadline_id,
                "deadline_type": deadline_type,
                "notification_number": notification_number,
                "original_deadline_ts": original_deadline_ts,
                "planned_delivery_time": planned_delivery_time,
                "status": "scheduled",
            }

            await db_manager.create_scheduled_notification(notification_data)
            return True

        except Exception as e:
            logger.error(f"Ошибка создания запланированного уведомления: {e}")
            return False

    async def reschedule_notifications_for_updated_task(
        self, deadline: Task
    ) -> int:
        """Перепланировать уведомления для обновленного дедлайна"""
        try:
            cancelled_count = (
                await db_manager.cancel_scheduled_notifications_for_task(
                    deadline.id
                )
            )
            logger.info(
                f"Отменено {cancelled_count} уведомлений для обновленного дедлайна {deadline.id}"
            )

            # Также отменяем уведомления в чатах для этого дедлайна
            from src.bot.services.chat_notification_scheduler_service import (
                chat_notification_scheduler_service,
            )
            cancelled_in_chats = await chat_notification_scheduler_service.cancel_notifications_for_task(
                deadline.id
            )
            logger.info(
                f"(Чаты) Отменено {cancelled_in_chats} уведомлений для обновленного дедлайна {deadline.id}"
            )

            scheduled_count = await self.schedule_notifications_for_task(deadline)

            return scheduled_count

        except Exception as e:
            logger.error(
                f"Ошибка перепланирования уведомлений для дедлайна {deadline.id}: {e}"
            )
            return 0

    async def reschedule_notifications_for_user_settings_change(
        self, user_id: int
    ) -> int:
        """Перепланировать все уведомления пользователя при изменении настроек"""
        try:
            user_deadlines = await self._get_user_tasks(user_id)
            await self._cancel_notifications_for_tasks(user_id, user_deadlines)
            user, settings = await self._get_user_and_settings(user_id)
            total_rescheduled = await self._schedule_notifications_for_tasks(
                user, user_deadlines, settings
            )

            logger.info(
                f"(U) {user_id} - Перепланировано {total_rescheduled} уведомлений"
            )
            return total_rescheduled

        except ValueError as e:
            logger.info(str(e))
            return 0
        except Exception as e:
            logger.error(
                f"Ошибка перепланирования уведомлений для пользователя {user_id}: {e}"
            )
            return 0

    async def schedule_notifications_for_user_subscription(
        self, user_id: int, subject_id: int
    ) -> int:
        """Создать уведомления для пользователя при подписке на предмет"""
        try:
            user, settings = await self._get_user_and_settings(user_id)
            subject_deadlines = await self._get_subject_tasks(subject_id)
            total_scheduled = await self._schedule_notifications_for_tasks(
                user, subject_deadlines, settings
            )

            logger.info(
                f"Запланировано {total_scheduled} уведомлений для пользователя {user_id} по предмету {subject_id}"
            )
            return total_scheduled

        except ValueError as e:
            logger.info(str(e))
            return 0
        except Exception as e:
            logger.error(
                f"Ошибка планирования уведомлений для подписки пользователя {user_id} на предмет {subject_id}: {e}"
            )
            return 0

    async def schedule_notifications_for_user_settings_creation(
        self, user_id: int
    ) -> int:
        """Создать уведомления для пользователя при создании настроек уведомлений"""
        try:
            user_deadlines = await self._get_user_tasks(user_id)

            if not user_deadlines:
                logger.info(
                    f"Нет дедлайнов для планирования уведомлений пользователя {user_id}"
                )
                return 0

            user, settings = await self._get_user_and_settings(user_id)
            total_scheduled = await self._schedule_notifications_for_tasks(
                user, user_deadlines, settings
            )

            logger.info(
                f"Запланировано {total_scheduled} уведомлений для пользователя {user_id} при создании настроек"
            )
            return total_scheduled

        except ValueError as e:
            logger.info(str(e))
            return 0
        except Exception as e:
            logger.error(
                f"Ошибка планирования уведомлений для пользователя {user_id} при создании настроек: {e}"
            )
            return 0

    async def cancel_notifications_for_user_subscription(
        self, user_id: int, subject_id: int
    ) -> int:
        """Отменить уведомления пользователя при отписке от предмета"""
        try:
            subject_deadlines = await self._get_subject_tasks(subject_id)

            if not subject_deadlines:
                logger.info(
                    f"Нет дедлайнов для отмены уведомлений по предмету {subject_id}"
                )
                return 0

            total_cancelled = await self._cancel_notifications_for_tasks(
                user_id, subject_deadlines
            )

            logger.info(
                f"Отменено {total_cancelled} уведомлений для пользователя {user_id} по предмету {subject_id}"
            )
            return total_cancelled

        except Exception as e:
            logger.error(
                f"Ошибка отмены уведомлений для пользователя {user_id} по предмету {subject_id}: {e}"
            )
            return 0

    async def cancel_all_notifications_for_user(self, user_id: int) -> int:
        """Отменить все уведомления пользователя при отписке от всех предметов"""
        try:
            async with db_manager.async_session() as session:
                cancel_stmt = select(ScheduledNotification).where(
                    and_(
                        ScheduledNotification.user_id == user_id,
                        ScheduledNotification.status == "scheduled",
                    )
                )
                result = await session.execute(cancel_stmt)
                notifications_to_cancel = result.scalars().all()

                total_cancelled = 0
                for notification in notifications_to_cancel:
                    notification.status = "cancelled"
                    notification.updated_at = utc_now()
                    total_cancelled += 1

                await session.commit()

            logger.info(
                f"Отменено {total_cancelled} уведомлений для пользователя {user_id}"
            )
            return total_cancelled

        except Exception as e:
            logger.error(
                f"Ошибка отмены всех уведомлений для пользователя {user_id}: {e}"
            )
            return 0


notification_scheduler_service = NotificationSchedulerService()
