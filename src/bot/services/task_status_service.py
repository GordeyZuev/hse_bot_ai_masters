from sqlalchemy import and_, delete, select
from sqlalchemy.dialects.postgresql import insert

from src.bot.services.user_action_events import add_user_action_event
from src.core.database import db_manager
from src.core.models import ScheduledNotification, Task, TaskUserStatus
from src.utils import get_logger
from src.utils.time import utc_now


logger = get_logger()  # imports at top per project preference


class TaskStatusService:
    async def set_done(
        self, user_id: int, deadline_id: int, *, surface: str | None = None
    ) -> bool:
        async with db_manager.async_session() as session:
            result = await session.execute(
                insert(TaskUserStatus)
                .values(user_id=user_id, deadline_id=deadline_id)
                .on_conflict_do_nothing(
                    index_elements=[TaskUserStatus.user_id, TaskUserStatus.deadline_id]
                )
                .returning(TaskUserStatus.user_id)
            )
            changed = result.scalar_one_or_none() is not None

            # cancel scheduled notifications for this user+deadline
            cancel_stmt = select(ScheduledNotification).where(
                and_(
                    ScheduledNotification.user_id == user_id,
                    ScheduledNotification.deadline_id == deadline_id,
                    ScheduledNotification.status.in_(
                        ["scheduled", "processing", "retry"]
                    ),
                )
            )
            res = await session.execute(cancel_stmt)
            for notif in res.scalars().all():
                notif.status = "cancelled"
                notif.updated_at = utc_now()

            if changed:
                add_user_action_event(
                    session,
                    user_id=user_id,
                    event_name="task_completed",
                    surface=surface,
                    task_id=deadline_id,
                )
            await session.commit()
            if changed:
                logger.info(f"(U) {user_id} - ДЗ {deadline_id} отмечено выполненным")
            return changed

    async def set_not_done(
        self, user_id: int, deadline_id: int, *, surface: str | None = None
    ) -> bool:
        async with db_manager.async_session() as session:
            result = await session.execute(
                delete(TaskUserStatus)
                .where(
                    and_(
                        TaskUserStatus.user_id == user_id,
                        TaskUserStatus.deadline_id == deadline_id,
                    )
                )
                .returning(TaskUserStatus.user_id)
            )
            changed = result.scalar_one_or_none() is not None
            if changed:
                add_user_action_event(
                    session,
                    user_id=user_id,
                    event_name="task_returned_to_work",
                    surface=surface,
                    task_id=deadline_id,
                )
            await session.commit()
            if changed:
                logger.info(f"(U) {user_id} - ДЗ {deadline_id} возвращено в работу")
            else:
                return False

        # Reschedule notifications for this user+deadline (if still in future)
        try:
            async with db_manager.async_session() as session:
                d = await session.get(Task, deadline_id)
            if not d:
                return True

            from src.bot.services.notification_scheduler_service import (
                notification_scheduler_service,
            )

            (
                user,
                settings,
            ) = await notification_scheduler_service._get_user_and_settings(user_id)
            count = 0
            if d.soft_deadline_ts:
                count += await notification_scheduler_service._schedule_notifications_for_user_task(
                    user, d, "soft", d.soft_deadline_ts, settings
                )
            if d.hard_deadline_ts:
                count += await notification_scheduler_service._schedule_notifications_for_user_task(
                    user, d, "hard", d.hard_deadline_ts, settings
                )
            logger.debug(
                f"(U) {user_id} - Для ДЗ {deadline_id} пересоздано уведомлений: {count}"
            )
        except Exception as e:
            logger.error(
                f"Failed to reschedule after set_not_done for user {user_id}, deadline {deadline_id}: {e}"
            )
        return True


task_status_service = TaskStatusService()
