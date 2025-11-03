from sqlalchemy import and_, delete, select

from src.core.database import db_manager
from src.core.models import Deadline, ScheduledNotification, TaskUserStatus
from src.utils import get_logger
from src.utils.time import utc_now


logger = get_logger()  # imports at top per project preference


class TaskStatusService:
    async def set_done(self, user_id: int, deadline_id: int) -> None:
        async with db_manager.async_session() as session:
            await session.merge(TaskUserStatus(user_id=user_id, deadline_id=deadline_id))

            # cancel scheduled notifications for this user+deadline
            cancel_stmt = select(ScheduledNotification).where(
                and_(
                    ScheduledNotification.user_id == user_id,
                    ScheduledNotification.deadline_id == deadline_id,
                    ScheduledNotification.status == "scheduled",
                )
            )
            res = await session.execute(cancel_stmt)
            for notif in res.scalars().all():
                notif.status = "cancelled"
                notif.updated_at = utc_now()

            await session.commit()
            logger.debug(f"(U){user_id} set done for deadline {deadline_id}")

    async def set_not_done(self, user_id: int, deadline_id: int) -> None:
        async with db_manager.async_session() as session:
            await session.execute(
                delete(TaskUserStatus).where(
                    and_(
                        TaskUserStatus.user_id == user_id,
                        TaskUserStatus.deadline_id == deadline_id,
                    )
                )
            )
            await session.commit()

        # Reschedule notifications for this user+deadline (if still in future)
        try:
            async with db_manager.async_session() as session:
                d = await session.get(Deadline, deadline_id)
            if not d:
                return

            from src.bot.services.notification_scheduler_service import (
                notification_scheduler_service,
            )
            user, settings = await notification_scheduler_service._get_user_and_settings(
                user_id
            )
            count = 0
            if d.soft_deadline_ts:
                count += await notification_scheduler_service._schedule_notifications_for_user_deadline(
                    user, d, "soft", d.soft_deadline_ts, settings
                )
            if d.hard_deadline_ts:
                count += await notification_scheduler_service._schedule_notifications_for_user_deadline(
                    user, d, "hard", d.hard_deadline_ts, settings
                )
            logger.debug(
                f"(U){user_id} set not done for deadline {deadline_id}, rescheduled {count}"
            )
        except Exception as e:
            logger.error(
                f"Failed to reschedule after set_not_done for user {user_id}, deadline {deadline_id}: {e}"
            )


task_status_service = TaskStatusService()


