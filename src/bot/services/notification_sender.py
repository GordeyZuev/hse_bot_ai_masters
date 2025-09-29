from typing import List, Dict, Any
from datetime import datetime, timedelta, timezone
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import pytz

from src.core.database import db_manager
from src.core.models import User, Deadline, Subject, Subscription, UserNotificationSettings, ScheduledNotification
from src.bot.services.notification_service import notification_service
from src.utils import get_logger
from sqlalchemy import select, and_, or_

logger = get_logger()

class NotificationSender:
    """Сервис для отправки уведомлений о дедлайнах"""
    
    async def send_deadline_notifications(self, bot: Bot) -> Dict[str, int]:
        """Отправить уведомления о приближающихся дедлайнах"""
        try:
            logger.info("Начинаю отправку уведомлений о дедлайнах")
            
            # Получаем всех пользователей с активными настройками уведомлений
            users_to_notify = await self._get_users_for_notifications()
            
            if not users_to_notify:
                logger.info("Нет пользователей для уведомлений")
                return {'sent': 0, 'errors': 0, 'skipped': 0}
            
            sent_count = 0
            error_count = 0
            skipped_count = 0
            
            for user_data in users_to_notify:
                try:
                    user = user_data['user']
                    settings = user_data['settings']
                    
                    # Обрабатываем первое напоминание
                    if settings.reminder1_offset > 0:
                        notification_time = self._calculate_notification_time(
                            settings.reminder1_offset, settings.reminder1_unit
                        )
                        
                        deadlines_to_notify = await self._get_user_deadlines_for_notification(
                            user.tg_user_id, notification_time
                        )
                        
                        if deadlines_to_notify:
                            filtered_deadlines = await self._filter_already_notified_deadlines(
                                user.tg_user_id, deadlines_to_notify, 1
                            )
                            
                            if filtered_deadlines:
                                success = await self._send_notification_to_user(
                                    bot, user, filtered_deadlines, 1, settings.reminder1_offset, settings.reminder1_unit
                                )
                                
                                if success:
                                    sent_count += 1
                                    await self._log_sent_notifications(
                                        user.tg_user_id, filtered_deadlines, 1
                                    )
                                else:
                                    error_count += 1
                            else:
                                skipped_count += 1
                    
                    # Обрабатываем второе напоминание
                    if settings.reminder2_offset > 0:
                        notification_time = self._calculate_notification_time(
                            settings.reminder2_offset, settings.reminder2_unit
                        )
                        
                        deadlines_to_notify = await self._get_user_deadlines_for_notification(
                            user.tg_user_id, notification_time
                        )
                        
                        if deadlines_to_notify:
                            filtered_deadlines = await self._filter_already_notified_deadlines(
                                user.tg_user_id, deadlines_to_notify, 2
                            )
                            
                            if filtered_deadlines:
                                success = await self._send_notification_to_user(
                                    bot, user, filtered_deadlines, 2, settings.reminder2_offset, settings.reminder2_unit
                                )
                                
                                if success:
                                    sent_count += 1
                                    await self._log_sent_notifications(
                                        user.tg_user_id, filtered_deadlines, 2
                                    )
                                else:
                                    error_count += 1
                            else:
                                skipped_count += 1
                
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления пользователю {user_data['user'].tg_user_id}: {e}")
                    error_count += 1
            
            logger.info(f"Уведомления отправлены: {sent_count} успешно, {error_count} ошибок, {skipped_count} пропущено")
            
            return {
                'sent': sent_count,
                'errors': error_count,
                'skipped': skipped_count
            }
            
        except Exception as e:
            logger.error(f"Ошибка отправки уведомлений: {e}")
            return {'sent': 0, 'errors': 0, 'skipped': 0}
    
    async def _get_users_for_notifications(self) -> List[Dict[str, Any]]:
        """Получить пользователей с активными настройками уведомлений"""
        async with db_manager.async_session() as session:
            try:
                
                # Получаем пользователей с активными настройками уведомлений и подписками
                stmt = select(User).join(UserNotificationSettings).join(Subscription).where(
                    UserNotificationSettings.is_active == True
                ).distinct()
                
                result = await session.execute(stmt)
                users = result.scalars().all()
                
                users_data = []
                for user in users:
                    # Получаем настройки уведомлений для каждого пользователя
                    settings = await notification_service.get_user_notification_settings(user.tg_user_id)
                    if settings and settings.is_active:
                        users_data.append({
                            'user': user,
                            'settings': settings
                        })
                
                return users_data
                
            except Exception as e:
                logger.error(f"Ошибка получения пользователей для уведомлений: {e}")
                return []
    
    def _calculate_notification_time(self, offset_value: int, offset_unit: str) -> Dict[str, datetime]:
        """Вычислить временной диапазон для уведомления (UTC)"""
        now = datetime.now(timezone.utc)
        
        if offset_unit == 'days':
            hours_offset = offset_value * 24
        elif offset_unit == 'hours':
            hours_offset = offset_value
        else:
            hours_offset = 24  # По умолчанию 24 часа
        
        # Временной диапазон: от (offset - 1 час) до (offset + 1 час)
        # Это позволяет отправлять уведомления в нужное время с небольшим допуском
        start_time = now + timedelta(hours=hours_offset - 1)
        end_time = now + timedelta(hours=hours_offset + 1)
        
        return {
            'start': start_time,
            'end': end_time,
            'offset_hours': hours_offset
        }
    
    async def _get_user_deadlines_for_notification(
        self, user_id: int, notification_time: Dict[str, datetime]
    ) -> List[Dict[str, Any]]:
        """Получить дедлайны пользователя для уведомления"""
        async with db_manager.async_session() as session:
            try:
                
                # Получаем подписки пользователя
                subscriptions_stmt = select(Subscription.subject_id).where(
                    Subscription.user_id == user_id
                )
                subscriptions_result = await session.execute(subscriptions_stmt)
                subscribed_subject_ids = [row[0] for row in subscriptions_result.fetchall()]
                
                if not subscribed_subject_ids:
                    return []
                
                start_time = notification_time['start']
                end_time = notification_time['end']
                
                # Получаем дедлайны в нужном временном диапазоне
                stmt = select(Deadline, Subject).join(Subject).where(
                    and_(
                        Deadline.subject_id.in_(subscribed_subject_ids),
                        or_(
                            and_(
                                Deadline.soft_deadline_ts.isnot(None),
                                Deadline.soft_deadline_ts >= start_time,
                                Deadline.soft_deadline_ts <= end_time
                            ),
                            and_(
                                Deadline.hard_deadline_ts.isnot(None),
                                Deadline.hard_deadline_ts >= start_time,
                                Deadline.hard_deadline_ts <= end_time
                            )
                        )
                    )
                )
                
                result = await session.execute(stmt)
                deadlines_data = []
                
                for deadline, subject in result.fetchall():
                    deadlines_data.append({
                        'deadline': deadline,
                        'subject': subject
                    })
                
                return deadlines_data
                
            except Exception as e:
                logger.error(f"Ошибка получения дедлайнов для уведомления пользователя {user_id}: {e}")
                return []
    
    async def _filter_already_notified_deadlines(
        self, user_id: int, deadlines_data: List[Dict[str, Any]], notification_number: int
    ) -> List[Dict[str, Any]]:
        """Фильтровать дедлайны, о которых уже отправлялись уведомления"""
        async with db_manager.async_session() as session:
            try:
                
                # Получаем уже отправленные уведомления
                deadline_ids = [data['deadline'].id for data in deadlines_data]
                
                stmt = select(NotificationLog.deadline_id).where(
                    NotificationLog.user_id == user_id,
                    NotificationLog.deadline_id.in_(deadline_ids),
                    NotificationLog.notification_type == f"notification_{notification_number}",
                    NotificationLog.status == 'sent'
                )
                
                result = await session.execute(stmt)
                notified_deadline_ids = set(row[0] for row in result.fetchall())
                
                filtered_deadlines = [
                    data for data in deadlines_data
                    if data['deadline'].id not in notified_deadline_ids
                ]
                
                return filtered_deadlines
                
            except Exception as e:
                logger.error(f"Ошибка фильтрации уведомлений: {e}")
                return deadlines_data
    
    async def _send_notification_to_user(
        self, bot: Bot, user: User, deadlines_data: List[Dict[str, Any]], 
        notification_number: int, offset_value: int, offset_unit: str
    ) -> bool:
        """Отправить уведомление пользователю"""
        try:
            if len(deadlines_data) == 1:
                data = deadlines_data[0]
                message_text = self._format_single_deadline_notification(user, data, notification_number, offset_value, offset_unit)
            else:
                message_text = self._format_multiple_deadlines_notification(user, deadlines_data, notification_number, offset_value, offset_unit)
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📅 Дедлайны", callback_data="quick_deadlines")]
            ])

            await bot.send_message(
                chat_id=user.tg_user_id,
                text=message_text,
                parse_mode='HTML',
                disable_web_page_preview=True,
                reply_markup=keyboard
            )
            
            logger.info(f"Уведомление отправлено пользователю {user.tg_user_id}")
            return True
            
        except TelegramForbiddenError:
            logger.warning(f"Пользователь {user.tg_user_id} заблокировал бота")
            return False
        except TelegramBadRequest as e:
            logger.warning(f"Ошибка отправки пользователю {user.tg_user_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Неожиданная ошибка отправки пользователю {user.tg_user_id}: {e}")
            return False
    
    def _format_single_deadline_notification(
        self, user: User, deadline_data: Dict[str, Any], notification_number: int, offset_value: int, offset_unit: str
    ) -> str:
        """Форматировать уведомление об одном дедлайне"""
        deadline = deadline_data['deadline']
        subject = deadline_data['subject']
        
        unit_text = {
            'days': 'дн.',
            'hours': 'ч.'
        }.get(offset_unit, offset_unit)
        
        message = f"🔔 <b>Напоминание о дедлайне</b>\n\n"
        message += f"📚 <b>Предмет:</b> {subject.name}\n"
        
        # Задание с гиперссылкой, если есть ссылка
        if deadline.source_link:
            message += f"📝 <b>Задание:</b> <a href='{deadline.source_link}'>{deadline.hw_name}</a>\n"
        else:
            message += f"📝 <b>Задание:</b> {deadline.hw_name}\n"
        
        # Информация о дедлайнах
        user_tz = pytz.timezone(getattr(user, 'timezone', '') or 'UTC')
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
                stmt_users = select(User).join(Subscription).where(Subscription.subject_id == deadline.subject_id)
                res_users = await session.execute(stmt_users)
                users = list(res_users.scalars().all())

                stmt_subject = select(Subject).where(Subject.id == deadline.subject_id)
                res_subject = await session.execute(stmt_subject)
                subject = res_subject.scalar_one_or_none()

            if not users:
                return 0

            action_text = 'Дедлайн обновлён'
            subject_name = subject.name if subject else 'Предмет'
            soft = deadline.soft_deadline_ts
            hard = deadline.hard_deadline_ts

            sent = 0
            for user in users:
                try:
                    settings = await db_manager.get_user_notification_settings(user.tg_user_id)
                    if not settings.is_active:
                        continue
                    user_tz = pytz.timezone(user.timezone) if user and user.timezone else pytz.UTC

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

                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📅 Дедлайны", callback_data="quick_deadlines")]
                    ])
                    
                    await bot.send_message(user.tg_user_id, message, parse_mode='HTML', disable_web_page_preview=True, reply_markup=keyboard)
                    sent += 1
                except TelegramForbiddenError:
                    logger.warning(f"Пользователь {user.tg_user_id} заблокировал бота")
                except TelegramBadRequest as e:
                    logger.warning(f"Ошибка отправки пользователю {user.tg_user_id}: {e}")
                except Exception as e:
                    logger.error(f"Неожиданная ошибка отправки пользователю {user.tg_user_id}: {e}")

            logger.info(f"Отправлено {sent} мгновенных уведомлений об обновлении дедлайна {deadline.id}")
            return sent
        except Exception as e:
            logger.error(f"Ошибка мгновенной отправки для дедлайна {deadline.id}: {e}")
            return 0

    async def send_immediate_deadline_changes(self, bot: Bot, deadlines: List[Deadline]) -> Dict[str, int]:
        """Отправить одно групповое сообщение пользователю, если за синхронизацию изменилось несколько дедлайнов."""
        stats = { 'users_processed': 0, 'messages_sent': 0 }
        try:
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
                subs_stmt = select(Subscription.user_id, Subscription.subject_id).where(Subscription.subject_id.in_(subject_ids))
                subs_res = await session.execute(subs_stmt)
                user_to_subjects: Dict[int, set] = {}
                for uid, sid in subs_res.fetchall():
                    user_to_subjects.setdefault(uid, set()).add(sid)

            if not user_to_subjects:
                return stats

            # Готовим данные по пользователям: какие дедлайны им релевантны
            user_entries: Dict[int, List[Dict[str, Any]]] = {}
            for d in deadlines:
                sid = d.subject_id
                for uid, sids in user_to_subjects.items():
                    if sid in sids:
                        user_entries.setdefault(uid, []).append({'deadline': d, 'subject': subjects.get(sid)})

            # Загружаем пользователей и их настройки единым запросом
            user_ids = list(user_entries.keys())
            async with db_manager.async_session() as session:
                usr_stmt = select(User, UserNotificationSettings).join(
                    UserNotificationSettings, User.tg_user_id == UserNotificationSettings.user_id
                ).where(User.tg_user_id.in_(user_ids))
                usr_res = await session.execute(usr_stmt)
                rows = usr_res.fetchall()

            for user, settings in rows:
                try:
                    if not settings or not settings.is_active:
                        continue
                    entries = user_entries.get(user.tg_user_id) or []
                    if not entries:
                        continue

                    # Формируем единое сообщение о нескольких обновлениях
                    user_tz = pytz.timezone(user.timezone) if user and user.timezone else pytz.UTC
                    message = self._format_multiple_deadline_updates(entries, user_tz)
                    
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📅 Дедлайны", callback_data="quick_deadlines")]
                    ])
                    
                    await bot.send_message(user.tg_user_id, message, parse_mode='HTML', disable_web_page_preview=True, reply_markup=keyboard)
                    stats['messages_sent'] += 1
                    stats['users_processed'] += 1
                except TelegramForbiddenError:
                    logger.warning(f"Пользователь {user.tg_user_id} заблокировал бота")
                except TelegramBadRequest as e:
                    logger.warning(f"Ошибка отправки пользователю {user.tg_user_id}: {e}")
                except Exception as e:
                    logger.error(f"Неожиданная ошибка отправки пользователю {user.tg_user_id}: {e}")

            return stats
        except Exception as e:
            logger.error(f"Ошибка групповой мгновенной отправки: {e}")
            return stats

    def _format_multiple_deadline_updates(self, entries: List[Dict[str, Any]], user_tz) -> str:
        """Сформировать сообщение о нескольких обновлениях дедлайнов (без расчётов \"осталось\")."""
        message = f"📌 <b>Обновлены дедлайны ({len(entries)})</b>\n\n"
        # Сортируем по ближайшему времени дедлайна (soft/hard, что доступно)
        def deadline_key(e):
            d: Deadline = e['deadline']
            return min([dt for dt in [d.soft_deadline_ts, d.hard_deadline_ts] if dt is not None] or [datetime.max.replace(tzinfo=timezone.utc)])
        entries_sorted = sorted(entries, key=deadline_key)

        for i, e in enumerate(entries_sorted, 1):
            d: Deadline = e['deadline']
            s: Subject = e['subject']
            message += f"<b>{i}. {s.name if s else 'Предмет'}</b>\n"
            if d.source_link:
                message += f"📝 <a href='{d.source_link}'>{d.hw_name}</a>\n"
            else:
                message += f"📝 {d.hw_name}\n"
            if d.soft_deadline_ts:
                soft_local = d.soft_deadline_ts.astimezone(user_tz)
                message += f"🟡 <b>Мягкий дедлайн:</b> {soft_local.strftime('%d.%m.%Y в %H:%M')}\n"
            if d.hard_deadline_ts:
                hard_local = d.hard_deadline_ts.astimezone(user_tz)
                message += f"🔴 <b>Жёсткий дедлайн:</b> {hard_local.strftime('%d.%m.%Y в %H:%M')}\n"
            if d.note:
                message += f"💬 <i>{d.note}</i>\n"
            message += "\n"
        return message
    
    def _format_multiple_deadlines_notification(
        self, user: User, deadlines_data: List[Dict[str, Any]], notification_number: int, offset_value: int, offset_unit: str
    ) -> str:
        """Форматировать уведомление о нескольких дедлайнах"""
        unit_text = {
            'days': 'дн.',
            'hours': 'ч.'
        }.get(offset_unit, offset_unit)
        
        message = f"🔔 <b>Напоминания о дедлайнах ({len(deadlines_data)})</b>\n\n"
        
        user_tz = pytz.timezone(getattr(user, 'timezone', '') or 'UTC')
        for i, data in enumerate(deadlines_data, 1):
            deadline = data['deadline']
            subject = data['subject']
            
            message += f"<b>{i}. {subject.name}</b>\n"
            
            # Задание с гиперссылкой, если есть ссылка
            if deadline.source_link:
                message += f"📝 <a href='{deadline.source_link}'>{deadline.hw_name}</a>\n"
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
        self, user_id: int, deadlines_data: List[Dict[str, Any]], notification_number: int
    ):
        """Записать отправленные уведомления в лог"""
        async with db_manager.async_session() as session:
            try:
                current_time = datetime.now(timezone.utc)
                
                for data in deadlines_data:
                    deadline = data['deadline']
                    
                    log_entry = NotificationLog(
                        user_id=user_id,
                        deadline_id=deadline.id,
                        notification_type=f"notification_{notification_number}",
                        scheduled_for=current_time,
                        status='sent',
                        attempt_count=1,
                        sent_at=current_time
                    )
                    session.add(log_entry)
                
                await session.commit()
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка записи лога уведомлений: {e}")

notification_sender = NotificationSender()