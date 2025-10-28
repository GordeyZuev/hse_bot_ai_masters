from datetime import datetime, timedelta

from sqlalchemy import and_, delete, select
from sqlalchemy.dialects.postgresql import insert

from src.core.database import db_manager
from src.core.models import ChatGroup, ChatScheduledNotification, Deadline
from src.utils import get_logger
from src.utils.time import utc_now


logger = get_logger()


class ChatNotificationSchedulerService:
    """Сервис для планирования уведомлений в чатах"""

    def __init__(self):
        pass

    async def schedule_notifications_for_chat_subscription(self, chat_id: int, subject_id: int) -> int:
        """Создать запланированные уведомления для нового чата"""
        try:
            # Получаем чат
            async with db_manager.async_session() as session:
                stmt = select(ChatGroup).where(ChatGroup.chat_id == chat_id)
                result = await session.execute(stmt)
                chat_group = result.scalar_one_or_none()

                if not chat_group or not chat_group.is_active:
                    return 0

                # Получаем все активные дедлайны по предмету
                deadlines = await self._get_subject_deadlines(subject_id)

                if not deadlines:
                    return 0

                total_scheduled = 0

                for deadline in deadlines:
                    count = await self._schedule_notifications_for_chat_deadline(
                        chat_group, deadline
                    )
                    total_scheduled += count

                logger.info(f"(C) {chat_id} - Запланировано {total_scheduled} уведомлений")
                return total_scheduled

        except Exception as e:
            logger.error(f"Ошибка планирования уведомлений для чата {chat_id}: {e}")
            return 0

    async def schedule_notifications_for_deadline(self, deadline: Deadline) -> int:
        """Создать запланированные уведомления для дедлайна во всех чатах"""
        try:
            # Получаем все активные чаты по предмету
            async with db_manager.async_session() as session:
                stmt = select(ChatGroup).where(
                    and_(
                        ChatGroup.subject_id == deadline.subject_id,
                        ChatGroup.is_active
                    )
                )
                result = await session.execute(stmt)
                chat_groups = list(result.scalars().all())

                if not chat_groups:
                    return 0

                total_scheduled = 0

                for chat_group in chat_groups:
                    count = await self._schedule_notifications_for_chat_deadline(
                        chat_group, deadline
                    )
                    total_scheduled += count

                logger.info(f"Запланировано {total_scheduled} уведомлений для дедлайна {deadline.id} в чатах")
                return total_scheduled

        except Exception as e:
            logger.error(f"Ошибка планирования уведомлений для дедлайна {deadline.id}: {e}")
            return 0

    async def _get_subject_deadlines(self, subject_id: int) -> list[Deadline]:
        """Получить все активные дедлайны по предмету"""
        async with db_manager.async_session() as session:
            stmt = select(Deadline).where(Deadline.subject_id == subject_id)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def _schedule_notifications_for_chat_deadline(
        self, chat_group: ChatGroup, deadline: Deadline
    ) -> int:
        """Создать уведомления для чата по дедлайну"""
        try:
            total_scheduled = 0

            # Планируем уведомления для мягкого дедлайна
            if deadline.soft_deadline_ts:
                count = await self._create_chat_notifications(
                    chat_group, deadline, "soft", deadline.soft_deadline_ts
                )
                total_scheduled += count

            # Планируем уведомления для жесткого дедлайна
            if deadline.hard_deadline_ts:
                count = await self._create_chat_notifications(
                    chat_group, deadline, "hard", deadline.hard_deadline_ts
                )
                total_scheduled += count

            return total_scheduled

        except Exception as e:
            logger.error(f"Ошибка планирования уведомлений для чата {chat_group.chat_id} и дедлайна {deadline.id}: {e}")
            return 0

    async def _create_chat_notifications(
        self,
        chat_group: ChatGroup,
        deadline: Deadline,
        deadline_type: str,
        deadline_ts: datetime
    ) -> int:
        """Создать уведомления для чата"""
        try:
            notifications_created = 0

            # Первое напоминание
            if chat_group.reminder1_offset > 0:
                planned_time = self._calculate_notification_time(
                    deadline_ts, chat_group.reminder1_offset, chat_group.reminder1_unit
                )

                async with db_manager.async_session() as session:
                    stmt = (
                        insert(ChatScheduledNotification)
                        .values(
                            chat_group_id=chat_group.chat_id,
                            deadline_id=deadline.id,
                            deadline_type=deadline_type,
                            notification_number=1,
                            original_deadline_ts=deadline_ts,
                            planned_delivery_time=planned_time,
                            status="scheduled",
                        )
                        .on_conflict_do_nothing(
                            constraint="unique_chat_deadline_notification"
                        )
                    )
                    result = await session.execute(stmt)
                    # result.rowcount is None for INSERT .. DO NOTHING; check via inserted_primary_key or return value
                    # Commit regardless; count only if actually inserted
                    await session.commit()
                    if result.rowcount and result.rowcount > 0:
                        notifications_created += 1

            # Второе напоминание
            if chat_group.reminder2_offset > 0:
                planned_time = self._calculate_notification_time(
                    deadline_ts, chat_group.reminder2_offset, chat_group.reminder2_unit
                )

                async with db_manager.async_session() as session:
                    stmt = (
                        insert(ChatScheduledNotification)
                        .values(
                            chat_group_id=chat_group.chat_id,
                            deadline_id=deadline.id,
                            deadline_type=deadline_type,
                            notification_number=2,
                            original_deadline_ts=deadline_ts,
                            planned_delivery_time=planned_time,
                            status="scheduled",
                        )
                        .on_conflict_do_nothing(
                            constraint="unique_chat_deadline_notification"
                        )
                    )
                    result = await session.execute(stmt)
                    await session.commit()
                    if result.rowcount and result.rowcount > 0:
                        notifications_created += 1

            return notifications_created

        except Exception as e:
            logger.error(f"Ошибка создания уведомлений для чата {chat_group.chat_id}: {e}")
            return 0

    def _calculate_notification_time(
        self, deadline_ts: datetime, offset: int, unit: str
    ) -> datetime:
        """Вычислить время отправки уведомления"""
        if unit == "days":
            return deadline_ts - timedelta(days=offset)
        elif unit == "hours":
            return deadline_ts - timedelta(hours=offset)
        else:
            raise ValueError(f"Неподдерживаемая единица времени: {unit}")

    async def cancel_notifications_for_chat_deadline(
        self, chat_group: ChatGroup, deadline: Deadline
    ) -> int:
        """Отменить уведомления для чата по дедлайну"""
        try:
            async with db_manager.async_session() as session:
                stmt = select(ChatScheduledNotification).where(
                    and_(
                        ChatScheduledNotification.chat_group_id == chat_group.chat_id,
                        ChatScheduledNotification.deadline_id == deadline.id,
                        ChatScheduledNotification.status == "scheduled"
                    )
                )
                result = await session.execute(stmt)
                notifications = list(result.scalars().all())

                cancelled_count = 0
                for notification in notifications:
                    notification.status = "cancelled"
                    notification.updated_at = utc_now()
                    session.add(notification)
                    cancelled_count += 1

                await session.commit()
                return cancelled_count

        except Exception as e:
            logger.error(f"Ошибка отмены уведомлений для чата {chat_group.chat_id}: {e}")
            return 0

    async def reschedule_notifications_for_chat_settings_update(
        self, chat_group: ChatGroup
    ) -> int:
        """Перепланировать уведомления при изменении настроек чата"""
        try:
            # Получаем все активные уведомления чата
            async with db_manager.async_session() as session:
                stmt = select(ChatScheduledNotification).where(
                    and_(
                        ChatScheduledNotification.chat_group_id == chat_group.chat_id,
                        ChatScheduledNotification.status == "scheduled"
                    )
                )
                result = await session.execute(stmt)
                notifications = list(result.scalars().all())

                rescheduled_count = 0

                for notification in notifications:
                    # Отменяем старое уведомление
                    notification.status = "cancelled"
                    notification.updated_at = utc_now()

                    # Создаем новое уведомление с обновленными настройками
                    new_planned_time = self._calculate_notification_time(
                        notification.original_deadline_ts,
                        chat_group.reminder1_offset if notification.notification_number == 1 else chat_group.reminder2_offset,
                        chat_group.reminder1_unit if notification.notification_number == 1 else chat_group.reminder2_unit
                    )

                    new_notification = ChatScheduledNotification(
                        chat_group_id=chat_group.chat_id,
                        deadline_id=notification.deadline_id,
                        deadline_type=notification.deadline_type,
                        notification_number=notification.notification_number,
                        original_deadline_ts=notification.original_deadline_ts,
                        planned_delivery_time=new_planned_time
                    )

                    session.add(new_notification)
                    rescheduled_count += 1

                await session.commit()
                return rescheduled_count

        except Exception as e:
            logger.error(f"Ошибка перепланирования уведомлений для чата {chat_group.chat_id}: {e}")
            return 0


    async def reschedule_notifications_for_chat_subject_change(self, chat_id: int, new_subject_id: int) -> int:
        """Перепланирование уведомлений при смене дисциплины чата"""
        try:
            async with db_manager.async_session() as session:
                # Удаляем старые уведомления чата
                result = await session.execute(
                    delete(ChatScheduledNotification).where(
                        ChatScheduledNotification.chat_group_id == chat_id
                    )
                )
                deleted_count = result.rowcount

                # Получаем чат
                chat_group = await session.get(ChatGroup, chat_id)
                if not chat_group:
                    logger.error(f"Чат {chat_id} не найден")
                    return 0

                # Планируем новые уведомления для новой дисциплины
                scheduled_count = await self.schedule_notifications_for_chat_subscription(
                    chat_id, new_subject_id
                )

                logger.info(f"Перепланировано уведомлений для чата {chat_id}: удалено {deleted_count}, добавлено {scheduled_count}")
                return scheduled_count

        except Exception as e:
            logger.error(f"Ошибка перепланирования уведомлений при смене дисциплины чата {chat_id}: {e}")
            return 0


    async def cancel_chat_notifications(self, chat_id: int) -> int:
        """Отмена всех запланированных уведомлений чата (при удалении бота)"""
        try:
            async with db_manager.async_session() as session:
                from sqlalchemy import update

                # Обновляем статус всех запланированных уведомлений на 'cancelled'
                result = await session.execute(
                    update(ChatScheduledNotification)
                    .where(
                        ChatScheduledNotification.chat_group_id == chat_id,
                        ChatScheduledNotification.status == "scheduled"
                    )
                    .values(status="cancelled")
                )

                cancelled_count = result.rowcount
                await session.commit()

                logger.info(f"Отменено {cancelled_count} уведомлений для чата {chat_id}")
                return cancelled_count

        except Exception as e:
            logger.error(f"Ошибка отмены уведомлений для чата {chat_id}: {e}")
            return 0


# Создаем экземпляр сервиса
chat_notification_scheduler_service = ChatNotificationSchedulerService()
