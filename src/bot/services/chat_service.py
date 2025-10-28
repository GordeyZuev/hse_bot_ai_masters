
from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.core.database import db_manager
from src.core.models import ChatGroup, Subject
from src.utils import get_logger


logger = get_logger()


class ChatService:
    """Сервис для работы с групповыми чатами"""

    def __init__(self):
        pass

    async def get_chat_administrators(self, bot: Bot, chat_id: int) -> list[int]:
        """Получить список ID администраторов чата"""
        try:
            chat_member = await bot.get_chat_administrators(chat_id)
            return [admin.user.id for admin in chat_member]
        except Exception as e:
            logger.error(f"Ошибка получения админов чата {chat_id}: {e}")
            return []

    async def is_chat_admin(self, bot: Bot, chat_id: int, user_id: int) -> bool:
        """Проверка, является ли пользователь админом чата"""
        try:
            chat_member = await bot.get_chat_member(chat_id, user_id)
            return chat_member.status in ["administrator", "creator"]
        except Exception as e:
            logger.error(f"Ошибка проверки админа чата {chat_id}, пользователь {user_id}: {e}")
            return False

    async def bot_can_manage_topics(self, bot: Bot, chat_id: int) -> bool:
        """Проверить, есть ли у бота право управления топиками (forum topics)."""
        try:
            me = await bot.get_me()
            bot_member = await bot.get_chat_member(chat_id, me.id)
            # Для админа доступно поле can_manage_topics (в супергруппах с форумами)
            can_manage = getattr(getattr(bot_member, 'can_manage_topics', None), '__bool__', lambda: False)()
            # В некоторых реализациях атрибут может быть непосредственно булевым
            if isinstance(getattr(bot_member, 'can_manage_topics', None), bool):
                can_manage = bot_member.can_manage_topics
            return bool(can_manage)
        except Exception as e:
            logger.error(f"Ошибка проверки прав бота на управление топиками в чате {chat_id}: {e}")
            return False

    async def get_topic_title(self, bot: Bot, chat_id: int, message_thread_id: int | None) -> str | None:
        """Попробовать получить название топика по его message_thread_id.

        Возвращает строку названия или None, если получить нельзя/метода нет.
        """
        if not message_thread_id:
            return None
        try:
            # Bot API 6.3+: getForumTopic через high-level
            if hasattr(bot, "get_forum_topic"):
                topic = await bot.get_forum_topic(chat_id=chat_id, message_thread_id=message_thread_id)
                title = (
                    getattr(topic, "name", None)
                    or getattr(topic, "title", None)
                    or getattr(topic, "forum_topic", None) and getattr(topic.forum_topic, "name", None)
                )
                if title:
                    return str(title)

            # Fallback 1: низкоуровневый вызов через Bot.call_api
            try:
                raw = await bot.call_api("getForumTopic", chat_id=chat_id, message_thread_id=message_thread_id)
                if isinstance(raw, dict):
                    title = raw.get("name") or raw.get("title")
                    if title:
                        return str(title)
            except Exception as e_call_api:
                logger.debug(f"getForumTopic via call_api failed: {e_call_api}")

            # Fallback 2: прямой вызов через session.api.request
            try:
                raw2 = await bot.session.api.request("getForumTopic", {
                    "chat_id": chat_id,
                    "message_thread_id": message_thread_id,
                })
                if isinstance(raw2, dict):
                    title = raw2.get("name") or raw2.get("title")
                    if title:
                        return str(title)
            except Exception as e_req:
                logger.debug(f"getForumTopic via session.api.request failed: {e_req}")

        except Exception as e:
            logger.warning(f"Не удалось получить название топика {message_thread_id} чата {chat_id}: {e}")
        return None


    async def setup_chat_group(
        self,
        bot: Bot,
        chat_id: int,
        subject_id: int,
        admin_user_id: int,
        topic_id: int | None = None,
        *,
        reminder1_offset: int | None = None,
        reminder1_unit: str | None = None,
        reminder2_offset: int | None = None,
        reminder2_unit: str | None = None,
        is_active: bool | None = None,
    ) -> tuple[bool, str]:
        """Настроить чат на предмет"""
        async with db_manager.async_session() as session:
            try:
                # Проверяем, не настроен ли уже чат
                stmt = select(ChatGroup).where(ChatGroup.chat_id == chat_id)
                result = await session.execute(stmt)
                existing_chat = result.scalar_one_or_none()

                if existing_chat:
                    return False, "Этот чат уже настроен на предмет"

                # Проверяем права админа
                if not await self.is_chat_admin(bot, chat_id, admin_user_id):
                    return False, "Вы не являетесь администратором этого чата"

                # Получаем информацию о чате
                try:
                    chat_info = await bot.get_chat(chat_id)
                    chat_type = chat_info.type
                except Exception as e:
                    logger.error(f"Ошибка получения информации о чате {chat_id}: {e}")
                    return False, "Не удалось получить информацию о чате"

                # Проверяем существование предмета
                stmt = select(Subject).where(Subject.id == subject_id, Subject.is_active)
                result = await session.execute(stmt)
                subject = result.scalar_one_or_none()

                if not subject:
                    return False, "Предмет не найден или неактивен"

                # Создаем запись чата
                # Базовые значения по умолчанию
                r1_off = 7 if reminder1_offset is None else reminder1_offset
                r1_unit = "days" if reminder1_unit is None else reminder1_unit
                r2_off = 1 if reminder2_offset is None else reminder2_offset
                r2_unit = "days" if reminder2_unit is None else reminder2_unit
                active = False if is_active is None else is_active

                chat_group = ChatGroup(
                    chat_id=chat_id,
                    topic_id=topic_id,
                    chat_type=chat_type,
                    subject_id=subject_id,
                    reminder1_offset=r1_off,
                    reminder1_unit=r1_unit,
                    reminder2_offset=r2_off,
                    reminder2_unit=r2_unit,
                    is_active=active,
                )

                session.add(chat_group)
                await session.commit()

                logger.info(f"(C) {chat_id} - Настроен на предмет: «{subject.name}»")
                return True, f"Чат успешно настроен на предмет «{subject.name}»!"

            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка настройки {chat_id}: {e}")
                return False, "Произошла ошибка при настройке чата"

    async def get_chat_group(self, chat_id: int) -> ChatGroup | None:
        """Получить информацию о чате"""
        async with db_manager.async_session() as session:
            stmt = select(ChatGroup).options(selectinload(ChatGroup.subject)).where(ChatGroup.chat_id == chat_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_topic_id_from_message(self, message) -> int | None:
        """Получить topic_id из сообщения"""
        try:
            # Проверяем, есть ли topic_id в сообщении
            if hasattr(message, 'message_thread_id') and message.message_thread_id:
                return message.message_thread_id
            return None
        except Exception as e:
            logger.error(f"Ошибка получения topic_id из сообщения: {e}")
            return None

    async def is_chat_forum(self, bot: Bot, chat_id: int) -> bool:
        """Проверить, является ли чат форумом (поддерживает топики)"""
        try:
            chat_info = await bot.get_chat(chat_id)
            return hasattr(chat_info, 'forum_topic_created') and chat_info.forum_topic_created
        except Exception as e:
            logger.error(f"Ошибка проверки типа чата {chat_id}: {e}")
            return False

    async def update_chat_settings(
        self,
        chat_id: int,
        user_id: int,
        bot: Bot,
        reminder1_offset: int | None = None,
        reminder1_unit: str | None = None,
        reminder2_offset: int | None = None,
        reminder2_unit: str | None = None,
        topic_id: int | None = None,
        topic_title: str | None = None,
        *,
        topic_id_set: bool = False,
    ) -> tuple[bool, str]:
        """Обновить настройки уведомлений чата"""
        async with db_manager.async_session() as session:
            try:
                stmt = select(ChatGroup).where(ChatGroup.chat_id == chat_id)
                result = await session.execute(stmt)
                chat_group = result.scalar_one_or_none()

                if not chat_group:
                    return False, "Чат не настроен"

                # Проверяем права админа
                if not await self.is_chat_admin(bot, chat_id, user_id):
                    return False, "У вас нет прав для изменения настроек"

                # Обновляем настройки
                if reminder1_offset is not None:
                    chat_group.reminder1_offset = reminder1_offset
                if reminder1_unit is not None:
                    chat_group.reminder1_unit = reminder1_unit
                if reminder2_offset is not None:
                    chat_group.reminder2_offset = reminder2_offset
                if reminder2_unit is not None:
                    chat_group.reminder2_unit = reminder2_unit
                # Явное изменение топика (включая установку на общий чат = None)
                if topic_id_set:
                    chat_group.topic_id = topic_id
                    chat_group.topic_title = topic_title if topic_id is not None else None

                await session.commit()
                
                # Если изменился topic_id, перепланируем уведомления
                if topic_id_set:
                    from src.bot.services.chat_notification_scheduler_service import chat_notification_scheduler_service
                    await chat_notification_scheduler_service.reschedule_notifications_for_chat_settings_update(chat_group)
                
                return True, "Настройки успешно обновлены"

            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка обновления настроек чата {chat_id}: {e}")
                return False, "Произошла ошибка при обновлении настроек"

    async def toggle_chat_active(self, chat_id: int, user_id: int, bot: Bot) -> tuple[bool, str]:
        """Переключить активность уведомлений в чате"""
        async with db_manager.async_session() as session:
            try:
                stmt = select(ChatGroup).where(ChatGroup.chat_id == chat_id)
                result = await session.execute(stmt)
                chat_group = result.scalar_one_or_none()

                if not chat_group:
                    return False, "Чат не настроен"

                # Проверяем права админа
                if not await self.is_chat_admin(bot, chat_id, user_id):
                    return False, "У вас нет прав для изменения настроек"

                chat_group.is_active = not chat_group.is_active
                await session.commit()

                status = "включены" if chat_group.is_active else "отключены"
                return True, f"Уведомления в чате {status}"

            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка переключения активности чата {chat_id}: {e}")
                return False, "Произошла ошибка при изменении настроек"

    async def get_all_chat_groups(self) -> list[ChatGroup]:
        """Получить все настроенные чаты"""
        async with db_manager.async_session() as session:
            try:
                stmt = select(ChatGroup).options(selectinload(ChatGroup.subject)).order_by(ChatGroup.created_at.desc())
                result = await session.execute(stmt)
                return list(result.scalars().all())
            except Exception as e:
                logger.error(f"Ошибка получения списка чатов: {e}")
                return []

    async def get_chat_groups_count(self) -> int:
        """Получить количество настроенных чатов"""
        async with db_manager.async_session() as session:
            try:
                stmt = select(ChatGroup)
                result = await session.execute(stmt)
                return len(result.scalars().all())
            except Exception as e:
                logger.error(f"Ошибка подсчета чатов: {e}")
                return 0

    async def get_active_chat_groups_count(self) -> int:
        """Получить количество активных чатов"""
        async with db_manager.async_session() as session:
            try:
                stmt = select(ChatGroup).where(ChatGroup.is_active)
                result = await session.execute(stmt)
                return len(result.scalars().all())
            except Exception as e:
                logger.error(f"Ошибка подсчета активных чатов: {e}")
                return 0


    async def change_chat_subject(self, bot: Bot, chat_id: int, new_subject_id: int, user_id: int) -> tuple[bool, str]:
        """Смена дисциплины чата"""
        try:
            async with db_manager.async_session() as session:
                # Получаем чат вместе с текущей дисциплиной, чтобы не вызывать ленивую загрузку
                from sqlalchemy.orm import selectinload
                stmt = select(ChatGroup).options(selectinload(ChatGroup.subject)).where(ChatGroup.chat_id == chat_id)
                result = await session.execute(stmt)
                chat_group = result.scalar_one_or_none()
                if not chat_group:
                    return False, "❌ Чат не найден"

                # Проверяем права доступа
                if not await self.is_chat_admin(bot, chat_id, user_id):
                    return False, "❌ У вас нет прав для изменения дисциплины чата"

                # Получаем новую дисциплину
                new_subject = await session.get(Subject, new_subject_id)
                if not new_subject:
                    return False, "❌ Дисциплина не найдена"

                # Обновляем дисциплину
                old_subject_name = chat_group.subject.name if chat_group.subject else "—"
                chat_group.subject_id = new_subject_id

                await session.commit()

                logger.info(
                    f"Дисциплина чата {chat_id} изменена с '{old_subject_name}' на '{new_subject.name}'"
                )

                return True, f"✅ Дисциплина изменена с '{old_subject_name}' на '{new_subject.name}'"

        except Exception as e:
            logger.error(f"Ошибка смены дисциплины чата {chat_id}: {e}")
            return False, "❌ Произошла ошибка при смене дисциплины"


    async def deactivate_chat(self, chat_id: int) -> bool:
        """Деактивация чата (при удалении бота)"""
        try:
            async with self.db_manager.get_session() as session:
                chat_group = await session.get(ChatGroup, chat_id)
                if chat_group:
                    chat_group.is_active = False
                    await session.commit()
                    logger.info(f"Чат {chat_id} деактивирован")
                    return True
                return False
        except Exception as e:
            logger.error(f"Ошибка деактивации чата {chat_id}: {e}")
            return False

    async def activate_chat(self, chat_id: int) -> bool:
        """Активация чата (при повторном добавлении бота)"""
        try:
            async with self.db_manager.get_session() as session:
                chat_group = await session.get(ChatGroup, chat_id)
                if chat_group:
                    chat_group.is_active = True
                    await session.commit()
                    logger.info(f"Чат {chat_id} активирован")
                    return True
                return False
        except Exception as e:
            logger.error(f"Ошибка активации чата {chat_id}: {e}")
            return False


# Создаем экземпляр сервиса
chat_service = ChatService()
