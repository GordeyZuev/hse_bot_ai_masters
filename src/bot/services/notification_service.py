from datetime import UTC, datetime, time

from sqlalchemy import select

from src.bot.services.notification_scheduler_service import (
    notification_scheduler_service,
)
from src.core.database import db_manager
from src.core.models import UserNotificationSettings
from src.utils import get_logger


logger = get_logger()


class NotificationService:
    """Сервис для работы с настройками уведомлений пользователей"""

    def __init__(self):
        pass

    async def get_user_notification_settings(
        self, user_id: int
    ) -> UserNotificationSettings:
        """Получить настройки уведомлений пользователя"""
        try:
            return await db_manager.get_user_notification_settings(user_id)
        except Exception as e:
            logger.error(
                f"Ошибка получения настроек уведомлений пользователя {user_id}: {e}"
            )
            return await db_manager.create_user_notification_settings(user_id)

    async def set_user_notification(
        self,
        user_id: int,
        notification_number: int,
        offset_value: int,
        offset_unit: str,
    ) -> tuple[bool, str]:
        """Установить настройки уведомления для пользователя"""
        try:
            # Проверяем валидность параметров
            if notification_number not in [1, 2]:
                return False, "Номер уведомления должен быть 1 или 2"

            if offset_unit not in ["days", "hours"]:
                return False, "Единица времени должна быть: days или hours"

            if offset_value <= 0:
                return False, "Значение времени должно быть положительным"

            # Проверяем минимальное время уведомления (1 час)
            total_hours = self._convert_to_hours(offset_value, offset_unit)
            if total_hours < 1:
                return False, "Минимальное время уведомления - 1 час"

            # Получаем текущие настройки для проверки дублирования
            current_settings = await self.get_user_notification_settings(user_id)

            # Проверяем, что первое и второе уведомления не настроены одинаково
            if notification_number == 1:
                # Настраиваем первое уведомление - проверяем, не совпадает ли со вторым
                if (
                    current_settings.reminder2_offset == offset_value
                    and current_settings.reminder2_unit == offset_unit
                ):
                    return (
                        False,
                        "Первое и второе уведомления не могут быть настроены одинаково",
                    )
            else:
                # Настраиваем второе уведомление - проверяем, не совпадает ли с первым
                if (
                    current_settings.reminder1_offset == offset_value
                    and current_settings.reminder1_unit == offset_unit
                ):
                    return (
                        False,
                        "Первое и второе уведомления не могут быть настроены одинаково",
                    )

            # Готовим данные для обновления
            if notification_number == 1:
                settings_data = {
                    "reminder1_offset": offset_value,
                    "reminder1_unit": offset_unit,
                }
            else:
                settings_data = {
                    "reminder2_offset": offset_value,
                    "reminder2_unit": offset_unit,
                }

            # Обновляем настройки
            await db_manager.update_user_notification_settings(user_id, settings_data)

            # Перепланируем уведомления пользователя
            rescheduled_count = await notification_scheduler_service.reschedule_notifications_for_user_settings_change(
                user_id
            )

            unit_text = {"days": "дн.", "hours": "ч."}.get(offset_unit, offset_unit)

            logger.info(
                f"(U) {user_id} - Настроил уведомление {notification_number}: за {offset_value} {unit_text}. Перепланировано {rescheduled_count} уведомлений"
            )
            return True, f"Уведомление настроено: за {offset_value} {unit_text}"

        except Exception as e:
            logger.error(
                f"Ошибка настройки уведомления для пользователя {user_id}: {e}"
            )
            return False, "Произошла ошибка при настройке уведомления"

    async def toggle_notifications(
        self, user_id: int, is_enabled: bool
    ) -> tuple[bool, str]:
        """Включить/отключить все уведомления пользователя"""
        try:
            settings_data = {"is_active": is_enabled}
            await db_manager.update_user_notification_settings(user_id, settings_data)

            if is_enabled:
                # Если включаем уведомления, перепланируем их
                rescheduled_count = await notification_scheduler_service.reschedule_notifications_for_user_settings_change(
                    user_id
                )
                status_text = "включены"
                logger.info(
                    f"(U) {user_id} - Включил уведомления. Запланировано {rescheduled_count} уведомлений"
                )
            else:
                # Если выключаем, отменяем все запланированные уведомления пользователя
                async with db_manager.async_session() as session:
                    from sqlalchemy import and_

                    from src.core.models import ScheduledNotification

                    stmt = select(ScheduledNotification).where(
                        and_(
                            ScheduledNotification.user_id == user_id,
                            ScheduledNotification.status == "scheduled",
                        )
                    )
                    result = await session.execute(stmt)
                    notifications = result.scalars().all()

                    cancelled_count = 0
                    for notification in notifications:
                        notification.status = "cancelled"
                        notification.updated_at = datetime.now(UTC)
                        cancelled_count += 1

                    await session.commit()

                status_text = "отключены"
                logger.info(
                    f"(U) {user_id} - Отключил уведомления. Отменено {cancelled_count} уведомлений"
                )

            return True, f"Уведомления {status_text}"

        except Exception as e:
            logger.error(
                f"Ошибка переключения уведомлений для пользователя {user_id}: {e}"
            )
            return False, "Произошла ошибка при изменении настроек"

    async def set_sleep_time(
        self,
        user_id: int,
        sleep_start: time | None,
        sleep_end: time | None,
    ) -> tuple[bool, str]:
        """Установить время сна для пользователя"""
        try:
            settings_data = {
                "sleep_start_time": sleep_start,
                "sleep_end_time": sleep_end,
            }
            await db_manager.update_user_notification_settings(user_id, settings_data)

            if sleep_start is None or sleep_end is None:
                logger.info(f"(U) {user_id} - Время сна сброшено")
                return True, "Время сна отключено"
            else:
                start_str = sleep_start.strftime("%H:%M")
                end_str = sleep_end.strftime("%H:%M")
                logger.info(
                    f"(U) {user_id} - Время сна: {start_str} - {end_str}"
                )
                return True, f"Время сна установлено: {start_str} - {end_str}"

        except Exception as e:
            logger.error(f"Ошибка установки времени сна для пользователя {user_id}: {e}")
            return False, "Произошла ошибка при установке времени сна"

    async def toggle_deadline_update_notifications(
        self, user_id: int, is_enabled: bool
    ) -> tuple[bool, str]:
        """Включить/отключить уведомления об обновлении дедлайнов"""
        try:
            settings_data = {"enable_deadline_update_notifications": is_enabled}
            await db_manager.update_user_notification_settings(user_id, settings_data)

            status_text_log = "Включены" if is_enabled else "Отключены"
            status_text_user = "включены" if is_enabled else "отключены"
            logger.info(
                f"(U) {user_id} - {status_text_log} уведомления об обновлении дедлайнов"
            )
            return True, f"Уведомления об обновлениях {status_text_user}"

        except Exception as e:
            logger.error(
                f"Ошибка переключения уведомлений об обновлениях для пользователя {user_id}: {e}"
            )
            return False, "Произошла ошибка при изменении настроек"

    def _convert_to_hours(self, offset_value: int, offset_unit: str) -> int:
        """Конвертировать offset в часы"""
        if offset_unit == "hours":
            return offset_value
        elif offset_unit == "days":
            return offset_value * 24
        else:
            return 0


# Создаем экземпляр сервиса
notification_service = NotificationService()
