from datetime import UTC, datetime, timedelta
from typing import Any

import pytz
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import and_, or_, select

from src.core.database import db_manager
from src.core.models import (
    Deadline,
    Subject,
    Subscription,
    User,
    UserNotificationSettings,
)
from src.utils import get_logger


logger = get_logger()


class NotificationSender:
    """Сервис для отправки уведомлений о дедлайнах"""

    async def send_deadline_notifications(self, bot: Bot) -> dict[str, int]:
        """Отправить уведомления о приближающихся дедлайнах"""
        try:
            logger.info("Отправка уведомлений")

            # Получаем всех пользователей с активными настройками уведомлений
            users_to_notify = await self._get_users_for_notifications()

            if not users_to_notify:
                logger.info("Нет пользователей для уведомлений")
                return {"sent": 0, "errors": 0, "skipped": 0}

            sent_count = 0
            error_count = 0
            skipped_count = 0

            for user_data in users_to_notify:
                try:
                    user = user_data["user"]
                    settings = user_data["settings"]

                    # Обрабатываем первое напоминание
                    if settings.reminder1_offset > 0:
                        notification_time = self._calculate_notification_time(
                            settings.reminder1_offset, settings.reminder1_unit
                        )

                        deadlines_to_notify = (
                            await self._get_user_deadlines_for_notification(
                                user.tg_user_id, notification_time
                            )
                        )

                        if deadlines_to_notify:
                            success = await self._send_notification_to_user(
                                bot,
                                user,
                                deadlines_to_notify,
                                1,
                                settings.reminder1_offset,
                                settings.reminder1_unit,
                            )

                            if success:
                                sent_count += 1
                                await self._log_sent_notifications(
                                    user.tg_user_id, deadlines_to_notify, 1
                                )
                            else:
                                error_count += 1

                    # Обрабатываем второе напоминание
                    if settings.reminder2_offset > 0:
                        notification_time = self._calculate_notification_time(
                            settings.reminder2_offset, settings.reminder2_unit
                        )

                        deadlines_to_notify = (
                            await self._get_user_deadlines_for_notification(
                                user.tg_user_id, notification_time
                            )
                        )

                        if deadlines_to_notify:
                            success = await self._send_notification_to_user(
                                bot,
                                user,
                                deadlines_to_notify,
                                2,
                                settings.reminder2_offset,
                                settings.reminder2_unit,
                            )

                            if success:
                                sent_count += 1
                                await self._log_sent_notifications(
                                    user.tg_user_id, deadlines_to_notify, 2
                                )
                            else:
                                error_count += 1

                except Exception as e:
                    logger.error(
                        f"Ошибка отправки уведомления пользователю {user_data['user'].tg_user_id}: {e}"
                    )
                    error_count += 1

            logger.info(
                f"Уведомления отправлены: {sent_count} успешно, {error_count} ошибок, {skipped_count} пропущено"
            )

            return {"sent": sent_count, "errors": error_count, "skipped": skipped_count}

        except Exception as e:
            logger.error(f"Ошибка отправки уведомлений: {e}")
            return {"sent": 0, "errors": 0, "skipped": 0}

    async def _get_users_for_notifications(self) -> list[dict[str, Any]]:
        """Получить пользователей с активными настройками уведомлений"""
        async with db_manager.async_session() as session:
            try:
                # Получаем пользователей с активными настройками уведомлений и подписками
                stmt = (
                    select(User)
                    .join(UserNotificationSettings)
                    .join(Subscription)
                    .where(
                        and_(
                            UserNotificationSettings.is_active,
                            User.is_active  # Добавляем проверку активности пользователя
                        )
                    )
                    .distinct()
                )

                result = await session.execute(stmt)
                users = result.scalars().all()

                users_data = []
                for user in users:
                    # Получаем настройки уведомлений для каждого пользователя
                    settings = await db_manager.get_user_notification_settings(
                        user.tg_user_id
                    )
                    if settings and settings.is_active:
                        users_data.append({"user": user, "settings": settings})

                return users_data

            except Exception as e:
                logger.error(f"Ошибка получения пользователей для уведомлений: {e}")
                return []

    def _calculate_notification_time(
        self, offset_value: int, offset_unit: str
    ) -> dict[str, datetime]:
        """Вычислить временной диапазон для уведомления (UTC)"""
        now = datetime.now(UTC)

        if offset_unit == "days":
            hours_offset = offset_value * 24
        elif offset_unit == "hours":
            hours_offset = offset_value
        else:
            hours_offset = 24  # По умолчанию 24 часа

        # Временной диапазон: от (offset - 1 час) до (offset + 1 час)
        # Это позволяет отправлять уведомления в нужное время с небольшим допуском
        start_time = now + timedelta(hours=hours_offset - 1)
        end_time = now + timedelta(hours=hours_offset + 1)

        return {"start": start_time, "end": end_time, "offset_hours": hours_offset}

    async def _get_user_deadlines_for_notification(
        self, user_id: int, notification_time: dict[str, datetime]
    ) -> list[dict[str, Any]]:
        """Получить дедлайны пользователя для уведомления"""
        async with db_manager.async_session() as session:
            try:
                # Получаем подписки пользователя
                subscriptions_stmt = select(Subscription.subject_id).where(
                    Subscription.user_id == user_id
                )
                subscriptions_result = await session.execute(subscriptions_stmt)
                subscribed_subject_ids = [
                    row[0] for row in subscriptions_result.fetchall()
                ]

                if not subscribed_subject_ids:
                    return []

                start_time = notification_time["start"]
                end_time = notification_time["end"]

                # Получаем дедлайны в нужном временном диапазоне
                stmt = (
                    select(Deadline, Subject)
                    .join(Subject)
                    .where(
                        and_(
                            Deadline.subject_id.in_(subscribed_subject_ids),
                            or_(
                                and_(
                                    Deadline.soft_deadline_ts.isnot(None),
                                    Deadline.soft_deadline_ts >= start_time,
                                    Deadline.soft_deadline_ts <= end_time,
                                ),
                                and_(
                                    Deadline.hard_deadline_ts.isnot(None),
                                    Deadline.hard_deadline_ts >= start_time,
                                    Deadline.hard_deadline_ts <= end_time,
                                ),
                            ),
                        )
                    )
                )

                result = await session.execute(stmt)
                deadlines_data = []

                for deadline, subject in result.fetchall():
                    deadlines_data.append({"deadline": deadline, "subject": subject})

                return deadlines_data

            except Exception as e:
                logger.error(
                    f"Ошибка получения дедлайнов для уведомления пользователя {user_id}: {e}"
                )
                return []


    async def _send_notification_to_user(
        self,
        bot: Bot,
        user: User,
        deadlines_data: list[dict[str, Any]],
        notification_number: int,
        offset_value: int,
        offset_unit: str,
    ) -> bool:
        """Отправить уведомление пользователю"""
        try:
            if len(deadlines_data) == 1:
                data = deadlines_data[0]
                message_text = self._format_single_deadline_notification(
                    user, data, notification_number, offset_value, offset_unit
                )
            else:
                message_text = self._format_multiple_deadlines_notification(
                    user, deadlines_data, notification_number, offset_value, offset_unit
                )

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="📅 Дедлайны", callback_data="quick_deadlines"
                        )
                    ]
                ]
            )

            await bot.send_message(
                chat_id=user.tg_user_id,
                text=message_text,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=keyboard,
            )

            logger.info(f"(U) {user.tg_user_id} - Уведомление отправлено")
            return True

        except TelegramForbiddenError:
            logger.warning(f"(U) {user.tg_user_id} - Заблокирован")
            # Деактивируем пользователя при блокировке бота
            await self._deactivate_user(user.tg_user_id)
            return False
        except TelegramBadRequest as e:
            logger.warning(f"Ошибка отправки пользователю {user.tg_user_id}: {e}")
            # Деактивируем пользователя при ошибке отправки
            await self._deactivate_user(user.tg_user_id)
            return False
        except Exception as e:
            logger.error(
                f"Неожиданная ошибка отправки пользователю {user.tg_user_id}: {e}"
            )
            return False

    async def _deactivate_user(self, user_id: int):
        """Деактивировать пользователя при ошибке отправки уведомления"""
        try:
            async with db_manager.async_session() as session:
                user = await session.get(User, user_id)
                if user and user.is_active:
                    user.is_active = False
                    await session.commit()
                    logger.info(f"Пользователь {user_id} деактивирован из-за ошибки отправки уведомления")
        except Exception as e:
            logger.error(f"Ошибка деактивации пользователя {user_id}: {e}")

    def _format_single_deadline_notification(
        self,
        user: User,
        deadline_data: dict[str, Any],
        notification_number: int,
        offset_value: int,
        offset_unit: str,
    ) -> str:
        """Форматировать уведомление об одном дедлайне"""
        deadline = deadline_data["deadline"]
        subject = deadline_data["subject"]

        unit_text = {"days": "дн.", "hours": "ч."}.get(offset_unit, offset_unit)

        message = "🔔 <b>Напоминание о дедлайне</b>\n\n"
        message += f"📚 <b>Предмет:</b> {subject.name}\n"

        # Задание с гиперссылкой, если есть ссылка
        if deadline.source_link:
            message += f"📝 <b>Задание:</b> <a href='{deadline.source_link}'>{deadline.hw_name}</a>\n"
        else:
            message += f"📝 <b>Задание:</b> {deadline.hw_name}\n"

        # Информация о дедлайнах
        user_tz = pytz.timezone(getattr(user, "timezone", "") or "UTC")
        if deadline.soft_deadline_ts:
            soft_local = deadline.soft_deadline_ts.astimezone(user_tz)
            soft_date = soft_local.strftime("%d.%m.%Y в %H:%M")
            message += f"🟡 <b>Дедлайн:</b> {soft_date} (Осталось {offset_value} {unit_text})\n"

        if deadline.hard_deadline_ts:
            hard_local = deadline.hard_deadline_ts.astimezone(user_tz)
            hard_date = hard_local.strftime("%d.%m.%Y в %H:%M")
            message += f"🔴 <b>Дедлайн:</b> {hard_date} (Осталось {offset_value} {unit_text})\n"

        if deadline.note:
            message += f"\n💬 <i>{deadline.note}</i>"

        return message

    async def send_immediate_deadline_change(self, bot: Bot, deadline: Deadline) -> int:
        """Отправить мгновенное уведомление подписчикам о создании/изменении дедлайна"""
        try:
            async with db_manager.async_session() as session:
                stmt_users = (
                    select(User)
                    .join(Subscription)
                    .where(Subscription.subject_id == deadline.subject_id)
                )
                res_users = await session.execute(stmt_users)
                users = list(res_users.scalars().all())

                stmt_subject = select(Subject).where(Subject.id == deadline.subject_id)
                res_subject = await session.execute(stmt_subject)
                subject = res_subject.scalar_one_or_none()

            if not users:
                return 0

            action_text = "Дедлайн обновлён"
            subject_name = subject.name if subject else "Предмет"
            soft = deadline.soft_deadline_ts
            hard = deadline.hard_deadline_ts

            sent = 0
            for user in users:
                try:
                    settings = await db_manager.get_user_notification_settings(
                        user.tg_user_id
                    )
                    if not settings or not settings.is_active:
                        continue
                    
                    # Проверяем, включены ли уведомления об обновлениях
                    if not settings.enable_deadline_update_notifications:
                        continue
                    
                    user_tz = (
                        pytz.timezone(user.timezone)
                        if user and user.timezone
                        else pytz.UTC
                    )

                    message = f"📌 <b>{action_text}</b>\n\n"
                    message += f"📚 <b>Предмет:</b> {subject_name}\n"
                    if deadline.source_link:
                        message += f"📝 <b>Задание:</b> <a href='{deadline.source_link}'>{deadline.hw_name}</a>\n"
                    else:
                        message += f"📝 <b>Задание:</b> {deadline.hw_name}\n"
                    if soft:
                        soft_local = soft.astimezone(user_tz)
                        soft_str = soft_local.strftime("%d.%m.%Y в %H:%M")
                        message += f"🟡 <b>Мягкий дедлайн:</b> {soft_str}\n"
                    if hard:
                        hard_local = hard.astimezone(user_tz)
                        hard_str = hard_local.strftime("%d.%m.%Y в %H:%M")
                        message += f"🔴 <b>Жёсткий дедлайн:</b> {hard_str}\n"
                    if deadline.note:
                        message += f"\n💬 <i>{deadline.note}</i>"

                    # Проверяем время сна
                    is_sleep = False
                    user_tz_name = user.timezone if user.timezone else "Europe/Moscow"
                    from src.utils.time import is_sleep_time
                    is_sleep = is_sleep_time(
                        settings.sleep_start_time,
                        settings.sleep_end_time,
                        user_tz_name
                    )
                    
                    if is_sleep:
                        message = message + "\n\n\n<i>Отправлено без уведомления. Доброй ночи! 😴</i>"

                    keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="📅 Дедлайны", callback_data="quick_deadlines"
                                )
                            ]
                        ]
                    )

                    await bot.send_message(
                        user.tg_user_id,
                        message,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                        reply_markup=keyboard,
                        disable_notification=is_sleep,
                    )
                    sent += 1
                except TelegramForbiddenError:
                    logger.warning(f"(U) {user.tg_user_id} - Заблокирован")
                except TelegramBadRequest as e:
                    logger.warning(
                        f"Ошибка отправки пользователю {user.tg_user_id}: {e}"
                    )
                except Exception as e:
                    logger.error(
                        f"Неожиданная ошибка отправки пользователю {user.tg_user_id}: {e}"
                    )

            logger.info(
                f"Отправлено {sent} мгновенных уведомлений об обновлении дедлайна {deadline.id}"
            )
            return sent
        except Exception as e:
            logger.error(f"Ошибка мгновенной отправки для дедлайна {deadline.id}: {e}")
            return 0

    async def send_immediate_deadline_changes(
        self, bot: Bot, changes: list[dict[str, Any]]
    ) -> dict[str, int]:
        """Отправить одно групповое сообщение пользователю, если за синхронизацию изменилось несколько дедлайнов.
        
        Args:
            bot: Экземпляр бота для отправки сообщений
            changes: Список словарей с ключами "deadline" (Deadline) и "change_info" (dict с информацией об изменениях)
        """
        stats = {"users_processed": 0, "messages_sent": 0}
        try:
            if not changes:
                return stats

            # Извлекаем дедлайны из changes
            deadlines = [item["deadline"] for item in changes if "deadline" in item]
            if not deadlines:
                return stats

            # Загружаем Subjects одним запросом
            subject_ids = list({d.subject_id for d in deadlines if d and d.subject_id})
            async with db_manager.async_session() as session:
                sub_stmt = select(Subject).where(Subject.id.in_(subject_ids))
                sub_res = await session.execute(sub_stmt)
                subjects = {s.id: s for s in sub_res.scalars().all()}

                # Подписки пользователей на эти предметы
                from src.core.models import Subscription

                subs_stmt = select(Subscription.user_id, Subscription.subject_id).where(
                    Subscription.subject_id.in_(subject_ids)
                )
                subs_res = await session.execute(subs_stmt)
                user_to_subjects: dict[int, set] = {}
                for uid, sid in subs_res.fetchall():
                    user_to_subjects.setdefault(uid, set()).add(sid)

            if not user_to_subjects:
                return stats

            # Готовим данные по пользователям: какие дедлайны им релевантны с информацией об изменениях
            user_entries: dict[int, list[dict[str, Any]]] = {}
            for change_item in changes:
                d = change_item["deadline"]
                change_info = change_item.get("change_info", {})
                sid = d.subject_id
                for uid, sids in user_to_subjects.items():
                    if sid in sids:
                        user_entries.setdefault(uid, []).append({
                            "deadline": d,
                            "subject": subjects.get(sid),
                            "change_info": change_info
                        })

            # Загружаем пользователей и их настройки единым запросом
            user_ids = list(user_entries.keys())
            async with db_manager.async_session() as session:
                usr_stmt = (
                    select(User, UserNotificationSettings)
                    .join(
                        UserNotificationSettings,
                        User.tg_user_id == UserNotificationSettings.user_id,
                    )
                    .where(User.tg_user_id.in_(user_ids))
                )
                usr_res = await session.execute(usr_stmt)
                rows = usr_res.fetchall()

            for user, settings in rows:
                try:
                    if not settings or not settings.is_active:
                        continue
                    
                    # Проверяем, включены ли уведомления об обновлениях
                    if not settings.enable_deadline_update_notifications:
                        continue
                    
                    entries = user_entries.get(user.tg_user_id) or []
                    if not entries:
                        continue

                    # Формируем единое сообщение о нескольких обновлениях
                    user_tz = (
                        pytz.timezone(user.timezone)
                        if user and user.timezone
                        else pytz.UTC
                    )
                    message = self._format_multiple_deadline_updates(entries, user_tz)
                    
                    # Проверяем время сна
                    is_sleep = False
                    user_tz_name = user.timezone if user.timezone else "Europe/Moscow"
                    from src.utils.time import is_sleep_time
                    is_sleep = is_sleep_time(
                        settings.sleep_start_time,
                        settings.sleep_end_time,
                        user_tz_name
                    )
                    
                    if is_sleep:
                        message = message + "\n\n<i>Отправлено без уведомления. Доброй ночи! 😴</i>"

                    keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="📅 Дедлайны", callback_data="quick_deadlines"
                                )
                            ]
                        ]
                    )

                    await bot.send_message(
                        user.tg_user_id,
                        message,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                        reply_markup=keyboard,
                        disable_notification=is_sleep,
                    )
                    stats["messages_sent"] += 1
                    stats["users_processed"] += 1
                except TelegramForbiddenError:
                    logger.warning(f"(U) {user.tg_user_id} - Заблокирован")
                except TelegramBadRequest as e:
                    logger.warning(
                        f"Ошибка отправки пользователю {user.tg_user_id}: {e}"
                    )
                except Exception as e:
                    logger.error(
                        f"Неожиданная ошибка отправки пользователю {user.tg_user_id}: {e}"
                    )

            return stats
        except Exception as e:
            logger.error(f"Ошибка групповой мгновенной отправки: {e}")
            return stats

    def _format_multiple_deadline_updates(
        self, entries: list[dict[str, Any]], user_tz
    ) -> str:
        """Сформировать сообщение о нескольких обновлениях дедлайнов с указанием изменений."""
        from src.utils.notification_formatting import format_deadline_datetime_with_time_word

        # Разделяем новые и обновленные дедлайны
        new_deadlines = []
        updated_deadlines = []
        
        for e in entries:
            change_info = e.get("change_info", {})
            if change_info.get("is_new", False):
                new_deadlines.append(e)
            else:
                updated_deadlines.append(e)

        message_parts = []
        
        # Новые дедлайны
        if new_deadlines:
            message_parts.append(f"✨ <b>Новые дедлайны ({len(new_deadlines)})</b>\n")
            message_parts.append(self._format_deadline_list(new_deadlines, user_tz, is_new=True))
            message_parts.append("")

        # Обновленные дедлайны
        if updated_deadlines:
            message_parts.append(f"📌 <b>Обновлены дедлайны ({len(updated_deadlines)})</b>\n")
            message_parts.append(self._format_deadline_list(updated_deadlines, user_tz, is_new=False))
            message_parts.append("")

        return "\n".join(message_parts).strip()

    def _format_deadline_list(
        self, entries: list[dict[str, Any]], user_tz, is_new: bool = False
    ) -> str:
        """Форматировать список дедлайнов с информацией об изменениях."""
        from src.utils.notification_formatting import format_deadline_datetime_with_time_word

        # Сортируем по ближайшему времени дедлайна (soft/hard, что доступно)
        def deadline_key(e):
            d: Deadline = e["deadline"]
            return min(
                [
                    dt
                    for dt in [d.soft_deadline_ts, d.hard_deadline_ts]
                    if dt is not None
                ]
                or [datetime.max.replace(tzinfo=UTC)]
            )

        entries_sorted = sorted(entries, key=deadline_key)
        lines = []

        for i, e in enumerate(entries_sorted, 1):
            d: Deadline = e["deadline"]
            s: Subject = e["subject"]
            change_info = e.get("change_info", {})
            
            lines.append(f"<b>{i}. {s.name if s else 'Предмет'}</b>")
            if d.source_link:
                lines.append(f"📝 <a href='{d.source_link}'>{d.hw_name}</a>")
            else:
                lines.append(f"📝 {d.hw_name}")

            # Мягкий дедлайн
            if d.soft_deadline_ts:
                soft_str = format_deadline_datetime_with_time_word(d.soft_deadline_ts, user_tz.zone)
                
                if not is_new and change_info.get("soft_deadline_changed", False):
                    # Показываем изменение с перечеркнутым старым значением
                    old_soft = change_info.get("old_soft_deadline_ts")
                    if old_soft:
                        old_soft_str = format_deadline_datetime_with_time_word(old_soft, user_tz.zone)
                        lines.append(f"🟡 <b>Мягкий дедлайн:</b> {soft_str} (<s>{old_soft_str}</s>)")
                    else:
                        lines.append(f"🟡 <b>Мягкий дедлайн:</b> {soft_str} <i>(добавлен)</i>")
                else:
                    lines.append(f"🟡 <b>Мягкий дедлайн:</b> {soft_str}")

            # Жесткий дедлайн
            if d.hard_deadline_ts:
                hard_str = format_deadline_datetime_with_time_word(d.hard_deadline_ts, user_tz.zone)
                
                if not is_new and change_info.get("hard_deadline_changed", False):
                    # Показываем изменение с перечеркнутым старым значением
                    old_hard = change_info.get("old_hard_deadline_ts")
                    if old_hard:
                        old_hard_str = format_deadline_datetime_with_time_word(old_hard, user_tz.zone)
                        lines.append(f"🔴 <b>Жёсткий дедлайн:</b> {hard_str} (<s>{old_hard_str}</s>)")
                    else:
                        lines.append(f"🔴 <b>Жёсткий дедлайн:</b> {hard_str} <i>(добавлен)</i>")
                else:
                    lines.append(f"🔴 <b>Жёсткий дедлайн:</b> {hard_str}")

            if d.note:
                lines.append(f"💬 <i>{d.note}</i>")
            
            lines.append("")

        return "\n".join(lines)

    def _format_multiple_deadlines_notification(
        self,
        user: User,
        deadlines_data: list[dict[str, Any]],
        notification_number: int,
        offset_value: int,
        offset_unit: str,
    ) -> str:
        """Форматировать уведомление о нескольких дедлайнах"""
        unit_text = {"days": "дн.", "hours": "ч."}.get(offset_unit, offset_unit)

        message = f"🔔 <b>Напоминания о дедлайнах ({len(deadlines_data)})</b>\n\n"

        user_tz = pytz.timezone(getattr(user, "timezone", "") or "UTC")
        for i, data in enumerate(deadlines_data, 1):
            deadline = data["deadline"]
            subject = data["subject"]

            message += f"<b>{i}. {subject.name}</b>\n"

            # Задание с гиперссылкой, если есть ссылка
            if deadline.source_link:
                message += (
                    f"📝 <a href='{deadline.source_link}'>{deadline.hw_name}</a>\n"
                )
            else:
                message += f"📝 {deadline.hw_name}\n"

            if deadline.soft_deadline_ts:
                local_time = deadline.soft_deadline_ts.astimezone(user_tz)
                date_str = local_time.strftime("%d.%m.%Y в %H:%M")
                message += f"🟡 <b>Дедлайн:</b> {date_str} (Осталось {offset_value} {unit_text})\n"
            elif deadline.hard_deadline_ts:
                local_time = deadline.hard_deadline_ts.astimezone(user_tz)
                date_str = local_time.strftime("%d.%m.%Y в %H:%M")
                message += f"🔴 <b>Дедлайн:</b> {date_str} (Осталось {offset_value} {unit_text})\n"

            message += "\n"

        return message

    async def _log_sent_notifications(
        self,
        user_id: int,
        deadlines_data: list[dict[str, Any]],
        notification_number: int,
    ):
        """Записать отправленные уведомления в лог"""
        # NOTE: Этот метод больше не используется, так как отправка уведомлений
        # теперь происходит через ScheduledNotificationSender, который работает
        # с предрассчитанными ScheduledNotification.
        logger.debug(f"Уведомления отправлены пользователю {user_id} для {len(deadlines_data)} дедлайнов")


notification_sender = NotificationSender()
