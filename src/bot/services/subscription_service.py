
from sqlalchemy import delete, func, select

from src.bot.services.notification_scheduler_service import (
    notification_scheduler_service,
)
from src.core.database import db_manager
from src.core.models import Subject, Subscription
from src.utils import get_logger


logger = get_logger()


class SubscriptionService:
    """Сервис для работы с подписками пользователей"""

    async def get_subjects_by_year(self, year: int) -> list[Subject]:
        """Получить предметы по году обучения"""
        async with db_manager.async_session() as session:
            try:
                stmt = (
                    select(Subject)
                    .where(Subject.year == year, Subject.is_active)
                    .order_by(Subject.name)
                )
                result = await session.execute(stmt)
                return list(result.scalars().all())
            except Exception as e:
                logger.error(f"Ошибка получения предметов {year} курса: {e}")
                return []

    async def get_user_subscriptions(self, user_id: int) -> list[Subject]:
        """Получить подписки пользователя"""
        async with db_manager.async_session() as session:
            try:
                stmt = (
                    select(Subject)
                    .join(Subscription)
                    .where(Subscription.user_id == user_id)
                    .order_by(Subject.year, Subject.name)
                )
                result = await session.execute(stmt)
                return list(result.scalars().all())
            except Exception as e:
                logger.error(f"Ошибка получения подписок пользователя {user_id}: {e}")
                return []

    async def subscribe_user(self, user_id: int, subject_id: int) -> tuple[bool, str]:
        """Подписать пользователя на предмет"""
        async with db_manager.async_session() as session:
            try:
                # Проверяем, есть ли уже подписка
                stmt = select(Subscription).where(
                    Subscription.user_id == user_id,
                    Subscription.subject_id == subject_id,
                )
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()

                if existing:
                    return False, "Вы уже подписаны на этот предмет"

                # Создаем новую подписку
                subscription = Subscription(user_id=user_id, subject_id=subject_id)
                session.add(subscription)
                await session.commit()

                # Получаем название предмета для логирования
                stmt = select(Subject).where(Subject.id == subject_id)
                result = await session.execute(stmt)
                subject = result.scalar_one_or_none()
                subject_name = subject.name if subject else f"ID:{subject_id}"

                # Планируем уведомления для новой подписки
                scheduled_count = await notification_scheduler_service.schedule_notifications_for_user_subscription(
                    user_id, subject_id
                )

                logger.info(
                    f"(U) {user_id} - Подписка: {subject_name} ({scheduled_count} увед.)"
                )
                return True, "Подписка успешно оформлена!"

            except Exception as e:
                await session.rollback()
                logger.error(
                    f"Ошибка подписки пользователя {user_id} на предмет {subject_id}: {e}"
                )
                return False, "Произошла ошибка при оформлении подписки"

    async def unsubscribe_user(self, user_id: int, subject_id: int) -> tuple[bool, str]:
        """Отписать пользователя от предмета"""
        async with db_manager.async_session() as session:
            try:
                # Получаем название предмета для логирования
                stmt = select(Subject).where(Subject.id == subject_id)
                result = await session.execute(stmt)
                subject = result.scalar_one_or_none()
                subject_name = subject.name if subject else f"ID:{subject_id}"

                # Удаляем подписку
                stmt = delete(Subscription).where(
                    Subscription.user_id == user_id,
                    Subscription.subject_id == subject_id,
                )
                result = await session.execute(stmt)
                await session.commit()

                if result.rowcount > 0:
                    # Отменяем уведомления по этому предмету
                    cancelled_count = await notification_scheduler_service.cancel_notifications_for_user_subscription(
                        user_id, subject_id
                    )

                    logger.info(
                        f"(U) {user_id} - Отписка: {subject_name} (отменено {cancelled_count})"
                    )
                    return True, "Подписка успешно отменена!"
                else:
                    return False, "Вы не были подписаны на этот предмет"

            except Exception as e:
                await session.rollback()
                logger.error(
                    f"Ошибка отписки пользователя {user_id} от предмета {subject_id}: {e}"
                )
                return False, "Произошла ошибка при отмене подписки"

    async def unsubscribe_user_from_all(self, user_id: int) -> tuple[bool, str]:
        """Отписать пользователя от всех предметов"""
        async with db_manager.async_session() as session:
            try:
                stmt = delete(Subscription).where(Subscription.user_id == user_id)
                result = await session.execute(stmt)
                await session.commit()

                count = result.rowcount
                if count > 0:
                    # Отменяем все уведомления пользователя
                    cancelled_count = await notification_scheduler_service.cancel_all_notifications_for_user(
                        user_id
                    )

                    logger.info(
                        f"(U) {user_id} - Отписка от всех ({count}), отменено {cancelled_count}"
                    )
                    return True, f"Отменено {count} подписок"
                else:
                    return False, "У вас нет активных подписок"

            except Exception as e:
                await session.rollback()
                logger.error(
                    f"Ошибка отписки пользователя {user_id} от всех предметов: {e}"
                )
                return False, "Произошла ошибка при отмене подписок"

    async def get_subscription_stats(self) -> dict:
        """Получить статистику подписок"""
        async with db_manager.async_session() as session:
            try:
                # Общее количество подписок
                stmt = select(Subscription)
                result = await session.execute(stmt)
                total_subscriptions = len(result.scalars().all())

                # Количество уникальных пользователей с подписками
                stmt = select(Subscription.user_id).distinct()
                result = await session.execute(stmt)
                users_with_subscriptions = len(result.scalars().all())

                # Самые популярные предметы
                stmt = (
                    select(
                        Subject.name, func.count(Subscription.subject_id).label("count")
                    )
                    .join(Subscription)
                    .group_by(Subject.id, Subject.name)
                    .order_by(func.count(Subscription.subject_id).desc())
                    .limit(5)
                )
                result = await session.execute(stmt)
                popular_subjects = result.all()

                return {
                    "total_subscriptions": total_subscriptions,
                    "users_with_subscriptions": users_with_subscriptions,
                    "popular_subjects": popular_subjects,
                }

            except Exception as e:
                logger.error(f"Ошибка получения статистики подписок: {e}")
                return {}


# Создаем экземпляр сервиса
subscription_service = SubscriptionService()
