from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, select
from sqlalchemy.dialects.postgresql import insert

from src.core.database import db_manager
from src.core.models import ChatGroup, ChatScheduledNotification, ChatTopic, Task
from src.utils import get_logger
from src.utils.time import utc_now


logger = get_logger()


class ChatNotificationSchedulerService:
    """Сервис для планирования уведомлений в чатах"""

    def __init__(self):
        pass

    async def schedule_notifications_for_chat_subscription(
        self, chat_id: int, subject_id: int, chat_topic: ChatTopic | None = None
    ) -> int:
        """Создать запланированные уведомления для нового топика чата"""
        try:
            if chat_topic is None:
                # Получаем топик по subject_id и chat_id
                async with db_manager.async_session() as session:
                    from sqlalchemy import select
                    stmt = select(ChatTopic).where(
                        and_(
                            ChatTopic.chat_id == chat_id,
                            ChatTopic.subject_id == subject_id
                        )
                    ).limit(1)
                    result = await session.execute(stmt)
                    chat_topic = result.scalar_one_or_none()

            if not chat_topic or not chat_topic.is_active:
                return 0

            # Получаем все активные задачи по предмету
            deadlines = await self._get_subject_tasks(subject_id)

            if not deadlines:
                return 0

            total_scheduled = 0

            async with db_manager.async_session() as session:
                try:
                    for deadline in deadlines:
                        count = await self._schedule_notifications_for_chat_task(
                            session, chat_topic, deadline
                        )
                        total_scheduled += count
                    await session.commit()
                    logger.info(f"(C) {chat_id} (topic {chat_topic.topic_id}) - Запланировано {total_scheduled} уведомлений")
                    return total_scheduled
                except Exception as e:
                    await session.rollback()
                    logger.error(f"Ошибка планирования уведомлений для чата {chat_id}, откат транзакции: {e}")
                    raise

        except Exception as e:
            logger.error(f"Ошибка планирования уведомлений для чата {chat_id}: {e}")
            return 0

    async def schedule_notifications_for_task(self, deadline: Task) -> int:
        """Создать запланированные уведомления для дедлайна во всех топиках"""
        try:
            # Получаем все активные топики по предмету
            async with db_manager.async_session() as session:
                stmt = select(ChatTopic).where(
                    and_(
                        ChatTopic.subject_id == deadline.subject_id,
                        ChatTopic.is_active
                    )
                )
                result = await session.execute(stmt)
                chat_topics = list(result.scalars().all())

            if not chat_topics:
                return 0

            total_scheduled = 0

            async with db_manager.async_session() as session:
                try:
                    for chat_topic in chat_topics:
                        count = await self._schedule_notifications_for_chat_task(
                            session, chat_topic, deadline
                        )
                        total_scheduled += count
                    await session.commit()
                    logger.info(f"Запланировано {total_scheduled} уведомлений для дедлайна {deadline.id} в топиках")
                    return total_scheduled
                except Exception as e:
                    await session.rollback()
                    logger.error(f"Ошибка планирования уведомлений для дедлайна {deadline.id}, откат транзакции: {e}")
                    raise

        except Exception as e:
            logger.error(f"Ошибка планирования уведомлений для дедлайна {deadline.id}: {e}")
            return 0

    async def _get_subject_tasks(self, subject_id: int) -> list[Task]:
        """Получить все активные задачи по предмету"""
        async with db_manager.async_session() as session:
            stmt = select(Task).where(Task.subject_id == subject_id)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def _schedule_notifications_for_chat_task(
        self,
        session,
        chat_topic: ChatTopic,
        deadline: Task,
    ) -> int:
        """Создать уведомления для топика чата по задаче"""
        try:
            total_scheduled = 0

            # Планируем уведомления для мягкого дедлайна
            if deadline.soft_deadline_ts:
                count = await self._create_chat_notifications(
                    session, chat_topic, deadline, "soft", deadline.soft_deadline_ts
                )
                total_scheduled += count

            # Планируем уведомления для жесткого дедлайна
            if deadline.hard_deadline_ts:
                count = await self._create_chat_notifications(
                    session, chat_topic, deadline, "hard", deadline.hard_deadline_ts
                )
                total_scheduled += count

            return total_scheduled

        except Exception as e:
            logger.error(f"Ошибка планирования уведомлений для чата {chat_topic.chat_id} (topic {chat_topic.topic_id}) и дедлайна {deadline.id}: {e}")
            return 0

    async def _create_chat_notifications(
        self,
        session,
        chat_topic: ChatTopic,
        deadline: Task,
        deadline_type: str,
        deadline_ts: datetime,
    ) -> int:
        """Создать уведомления для топика чата"""
        try:
            notifications_created = 0

            # Первое напоминание
            if chat_topic.reminder1_offset > 0:
                planned_time = self._calculate_notification_time(
                    deadline_ts, chat_topic.reminder1_offset, chat_topic.reminder1_unit
                )
                # Пропускаем создание, если время уже в прошлом
                if planned_time > datetime.now(UTC):
                    stmt = (
                        insert(ChatScheduledNotification)
                        .values(
                            chat_topic_id=chat_topic.id,
                            chat_id=chat_topic.chat_id,
                            topic_id=chat_topic.topic_id,
                            deadline_id=deadline.id,
                            deadline_type=deadline_type,
                            notification_number=1,
                            original_deadline_ts=deadline_ts,
                            planned_delivery_time=planned_time,
                            status="scheduled",
                        )
                        .on_conflict_do_update(
                            constraint="unique_chat_topic_deadline_notification",
                            set_={
                                "status": "scheduled",
                                "planned_delivery_time": planned_time,
                                "original_deadline_ts": deadline_ts,
                                "updated_at": utc_now(),
                            },
                        )
                    )
                    result = await session.execute(stmt)
                    if result.rowcount and result.rowcount > 0:
                        notifications_created += 1

            # Второе напоминание
            if chat_topic.reminder2_offset > 0:
                planned_time = self._calculate_notification_time(
                    deadline_ts, chat_topic.reminder2_offset, chat_topic.reminder2_unit
                )
                # Пропускаем создание, если время уже в прошлом
                if planned_time > datetime.now(UTC):
                    stmt = (
                        insert(ChatScheduledNotification)
                        .values(
                            chat_topic_id=chat_topic.id,
                            chat_id=chat_topic.chat_id,
                            topic_id=chat_topic.topic_id,
                            deadline_id=deadline.id,
                            deadline_type=deadline_type,
                            notification_number=2,
                            original_deadline_ts=deadline_ts,
                            planned_delivery_time=planned_time,
                            status="scheduled",
                        )
                        .on_conflict_do_update(
                            constraint="unique_chat_topic_deadline_notification",
                            set_={
                                "status": "scheduled",
                                "planned_delivery_time": planned_time,
                                "original_deadline_ts": deadline_ts,
                                "updated_at": utc_now(),
                            },
                        )
                    )
                    result = await session.execute(stmt)
                    if result.rowcount and result.rowcount > 0:
                        notifications_created += 1

            return notifications_created

        except Exception as e:
            logger.error(f"Ошибка создания уведомлений для чата {chat_topic.chat_id} (topic {chat_topic.topic_id}): {e}")
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
        self, chat_topic: ChatTopic, deadline: Task
    ) -> int:
        """Отменить уведомления для топика чата по дедлайну"""
        try:
            async with db_manager.async_session() as session:
                stmt = select(ChatScheduledNotification).where(
                    and_(
                        ChatScheduledNotification.chat_topic_id == chat_topic.id,
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
            logger.error(f"Ошибка отмены уведомлений для чата {chat_topic.chat_id} (topic {chat_topic.topic_id}): {e}")
            return 0

    async def reschedule_notifications_for_chat_settings_update(
        self, chat_topic: ChatTopic
    ) -> int:
        """Перепланировать уведомления при изменении настроек топика чата"""
        try:
            # Получаем все активные уведомления топика
            async with db_manager.async_session() as session:
                stmt = select(ChatScheduledNotification).where(
                    and_(
                        ChatScheduledNotification.chat_topic_id == chat_topic.id,
                        ChatScheduledNotification.status == "scheduled"
                    )
                )
                result = await session.execute(stmt)
                notifications = list(result.scalars().all())

                rescheduled_count = 0

                for notification in notifications:
                    # Пересчитываем новое время по обновлённым настройкам
                    new_planned_time = self._calculate_notification_time(
                        notification.original_deadline_ts,
                        chat_topic.reminder1_offset if notification.notification_number == 1 else chat_topic.reminder2_offset,
                        chat_topic.reminder1_unit if notification.notification_number == 1 else chat_topic.reminder2_unit
                    )

                    # Обновляем существующую запись вместо вставки новой
                    notification.planned_delivery_time = new_planned_time
                    notification.status = "scheduled"
                    notification.updated_at = utc_now()
                    session.add(notification)
                    rescheduled_count += 1

                await session.commit()
                return rescheduled_count

        except Exception as e:
            logger.error(f"Ошибка перепланирования уведомлений для чата {chat_topic.chat_id} (topic {chat_topic.topic_id}): {e}")
            return 0

    async def cancel_notifications_for_task(self, deadline_id: int) -> int:
        """Отменить все запланированные уведомления в чатах для указанного дедлайна"""
        try:
            async with db_manager.async_session() as session:
                from sqlalchemy import update

                result = await session.execute(
                    update(ChatScheduledNotification)
                    .where(
                        ChatScheduledNotification.deadline_id == deadline_id,
                        ChatScheduledNotification.status == "scheduled",
                    )
                    .values(status="cancelled", updated_at=utc_now())
                )

                cancelled_count = result.rowcount or 0
                await session.commit()
                return cancelled_count

        except Exception as e:
            logger.error(
                f"Ошибка отмены уведомлений в чатах для дедлайна {deadline_id}: {e}"
            )
            return 0


    async def reschedule_notifications_for_chat_subject_change(self, chat_id: int, topic_id: int | None, new_subject_id: int) -> int:
        """Перепланирование уведомлений при смене дисциплины топика чата"""
        try:
            async with db_manager.async_session() as session:
                # Получаем чат для определения режима
                chat_group = await session.get(ChatGroup, chat_id)
                if not chat_group:
                    logger.error(f"Чат {chat_id} не найден")
                    return 0

                # Получаем топик с учетом режима
                if chat_group.mode == "single":
                    # В single-mode игнорируем topic_id и получаем единственный топик
                    from sqlalchemy import select
                    stmt = select(ChatTopic).where(ChatTopic.chat_id == chat_id)
                    result = await session.execute(stmt)
                    topics = list(result.scalars().all())
                    if not topics:
                        logger.error(f"Топик чата {chat_id} не найден (single-mode)")
                        return 0
                    if len(topics) > 1:
                        logger.error(f"В single-mode должен быть только один топик для чата {chat_id}")
                        return 0
                    chat_topic = topics[0]
                else:
                    # В multi-mode используем topic_id
                    from sqlalchemy import and_, select
                    stmt = select(ChatTopic).where(
                        and_(
                            ChatTopic.chat_id == chat_id,
                            ChatTopic.topic_id == topic_id if topic_id is not None else ChatTopic.topic_id.is_(None)
                        )
                    )
                    result = await session.execute(stmt)
                    chat_topic = result.scalar_one_or_none()

                    if not chat_topic:
                        logger.error(f"Топик чата {chat_id} (topic {topic_id}) не найден")
                        return 0

                # Удаляем старые уведомления
                await session.execute(
                    delete(ChatScheduledNotification).where(
                        ChatScheduledNotification.chat_topic_id == chat_topic.id
                    )
                )
                await session.commit()

            scheduled_count = await self.schedule_notifications_for_chat_subscription(
                chat_id, new_subject_id, chat_topic=chat_topic
            )

            logger.info(
                f"Перепланировано для чата {chat_id} (topic {topic_id}): обновлено {scheduled_count} уведомлений"
            )
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
                        ChatScheduledNotification.chat_id == chat_id,
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
