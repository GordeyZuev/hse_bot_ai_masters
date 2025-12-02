
import contextlib

from aiogram import Bot
from sqlalchemy import and_, select
from sqlalchemy.orm import selectinload

from src.core.database import db_manager
from src.core.models import Chat, ChatTopic, Subject
from src.utils import get_logger


logger = get_logger()


class ChatService:
    """Сервис для работы с групповыми чатами"""

    def __init__(self):
        pass

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
            if hasattr(bot_member, "can_manage_topics"):
                return bool(bot_member.can_manage_topics)
            return False
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
                    or (getattr(topic, "forum_topic", None) and getattr(topic.forum_topic, "name", None))
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
        mode: str | None = None,
        reminder1_offset: int | None = None,
        reminder1_unit: str | None = None,
        reminder2_offset: int | None = None,
        reminder2_unit: str | None = None,
        is_active: bool | None = None,
    ) -> tuple[bool, str]:
        """Настроить чат на предмет"""
        async with db_manager.async_session() as session:
            try:
                # Проверяем, не настроен ли уже чат (в текущей сессии)
                existing_chat = await session.get(Chat, chat_id)
                if not existing_chat and mode is None:
                    return False, "Сначала выберите режим работы бота"
                if existing_chat and mode is None:
                    mode = existing_chat.mode

                if existing_chat:
                    # Определяем режим для проверки
                    check_mode = mode if mode is not None else existing_chat.mode

                    if check_mode == "multi":
                        # В multi-mode проверяем, есть ли уже топик с таким topic_id
                        if topic_id is not None:
                            stmt = select(ChatTopic).where(
                                and_(
                                    ChatTopic.chat_id == chat_id,
                                    ChatTopic.topic_id == topic_id
                                )
                            )
                            result = await session.execute(stmt)
                            existing_topic = result.scalar_one_or_none()
                            if existing_topic:
                                return False, "Этот топик уже настроен на предмет"
                    else:
                        # В single-mode должен быть только один топик на весь чат
                        # Проверяем, есть ли уже любой топик (независимо от topic_id)
                        stmt = select(ChatTopic).where(ChatTopic.chat_id == chat_id)
                        result = await session.execute(stmt)
                        existing_topics = list(result.scalars().all())
                        # Если топик уже есть, он будет обновлен ниже в логике single-mode
                        # Здесь просто пропускаем проверку, чтобы не блокировать обновление

                # Проверяем права админа
                if not await self.is_chat_admin(bot, chat_id, admin_user_id):
                    return False, "Вы не являетесь администратором этого чата"

                # Валидация режима
                if mode == "multi" and topic_id is None:
                    return False, "В multi-mode нельзя настраивать общий чат (topic_id обязателен)"

                # Получаем информацию о чате
                try:
                    chat_info = await bot.get_chat(chat_id)
                    chat_type = chat_info.type
                    chat_title = getattr(chat_info, "title", None)
                    logger.debug(f"Получена информация о чате {chat_id}: тип={chat_type}, название={chat_title}")
                except Exception as e:
                    logger.error(f"Ошибка получения информации о чате {chat_id}: {e}")
                    return False, "Не удалось получить информацию о чате"

                # Проверяем существование предмета
                stmt = select(Subject).where(Subject.id == subject_id, Subject.is_active)
                result = await session.execute(stmt)
                subject = result.scalar_one_or_none()

                if not subject:
                    return False, "Предмет не найден или неактивен"

                # Базовые значения по умолчанию
                r1_off = 7 if reminder1_offset is None else reminder1_offset
                r1_unit = "days" if reminder1_unit is None else reminder1_unit
                r2_off = 1 if reminder2_offset is None else reminder2_offset
                r2_unit = "days" if reminder2_unit is None else reminder2_unit
                active = True if is_active is None else is_active

                # Проверяем, что первое и второе уведомления не настроены одинаково
                if r1_off == r2_off and r1_unit == r2_unit:
                    return (
                        False,
                        "Первое и второе уведомления не могут быть настроены одинаково",
                    )

                # Создаем или обновляем Chat
                if existing_chat:
                    chat = existing_chat
                    if mode is None:
                        mode = chat.mode
                    # Обновляем режим, если нужно
                    if chat.mode != mode:
                        chat.mode = mode
                else:
                    if mode is None:
                        return False, "Сначала выберите режим работы бота"
                    chat = Chat(
                        chat_id=chat_id,
                        mode=mode,
                        chat_title=chat_title,
                        chat_type=chat_type,
                    )
                    session.add(chat)
                    # Для нового чата нужно сделать flush, чтобы получить chat_id
                    await session.flush()

                # Валидация для single-mode: должен быть только один топик
                if mode == "single":
                    # Проверяем все существующие топики
                    stmt = select(ChatTopic).where(ChatTopic.chat_id == chat_id)
                    result = await session.execute(stmt)
                    existing_topics = list(result.scalars().all())

                    if existing_topics:
                        # В single-mode должен быть только один топик - обновляем его
                        if len(existing_topics) > 1:
                            return False, "В single-mode может быть только один топик. Переключите режим или удалите лишние топики."
                        # Обновляем существующий топик (независимо от его topic_id)
                        # В single-mode всегда обновляем существующий топик, даже если вызывается из другого топика
                        chat_topic = existing_topics[0]
                        chat_topic.topic_id = topic_id
                        chat_topic.subject_id = subject_id
                        chat_topic.reminder1_offset = r1_off
                        chat_topic.reminder1_unit = r1_unit
                        chat_topic.reminder2_offset = r2_off
                        chat_topic.reminder2_unit = r2_unit
                        chat_topic.is_active = active
                        # Обновляем название топика, если оно было передано
                        if topic_id is not None:
                            try:
                                topic_title = await self.get_topic_title(bot, chat_id, topic_id)
                                if topic_title:
                                    chat_topic.topic_title = topic_title
                            except Exception:
                                pass
                    else:
                        # Создаем новый топик (первый и единственный в single-mode)
                        # Получаем название топика, если возможно
                        topic_title = None
                        if topic_id is not None:
                            with contextlib.suppress(Exception):
                                topic_title = await self.get_topic_title(bot, chat_id, topic_id)

                        chat_topic = ChatTopic(
                            chat_id=chat_id,
                            topic_id=topic_id,
                            topic_title=topic_title,
                            subject_id=subject_id,
                            reminder1_offset=r1_off,
                            reminder1_unit=r1_unit,
                            reminder2_offset=r2_off,
                            reminder2_unit=r2_unit,
                            is_active=active,
                        )
                        session.add(chat_topic)
                else:
                    # Multi-mode: создаем новый топик
                    if topic_id is None:
                        return False, "В multi-mode topic_id обязателен"

                    chat_topic = ChatTopic(
                        chat_id=chat_id,
                        topic_id=topic_id,
                        subject_id=subject_id,
                        reminder1_offset=r1_off,
                        reminder1_unit=r1_unit,
                        reminder2_offset=r2_off,
                        reminder2_unit=r2_unit,
                        is_active=active,
                    )
                    session.add(chat_topic)

                await session.commit()

                logger.debug(f"Чат {chat_id} создан с названием: {chat_title}")

                logger.info(f"(C) {chat_id} - Настроен на предмет: «{subject.name}» (mode={mode})")
                return True, f"Чат успешно настроен на предмет «{subject.name}»!"

            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка настройки {chat_id}: {e}")
                return False, "Произошла ошибка при настройке чата"

    async def get_chat(self, chat_id: int) -> Chat | None:
        """Получить метаданные чата"""
        async with db_manager.async_session() as session:
            stmt = select(Chat).where(Chat.chat_id == chat_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_chat_topic(self, chat_id: int, topic_id: int | None = None) -> ChatTopic | None:
        """Получить настройки топика чата"""
        async with db_manager.async_session() as session:
            stmt = (
                select(ChatTopic)
                .options(selectinload(ChatTopic.subject))
                .where(
                    and_(
                        ChatTopic.chat_id == chat_id,
                        ChatTopic.topic_id == topic_id if topic_id is not None else ChatTopic.topic_id.is_(None)
                    )
                )
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_chat_group(self, chat_id: int) -> ChatTopic | None:
        """Получить информацию о чате (обратная совместимость)"""
        # Для обратной совместимости возвращаем ChatTopic
        # В single-mode это будет единственный топик
        async with db_manager.async_session() as session:
            # Сначала получаем чат, чтобы узнать режим
            chat = await self.get_chat(chat_id)
            if not chat:
                return None

            # Получаем топик (в single-mode будет один, в multi-mode нужен topic_id)
            if chat.mode == "single":
                # В single-mode возвращаем единственный топик
                stmt = (
                    select(ChatTopic)
                    .options(selectinload(ChatTopic.subject))
                    .where(ChatTopic.chat_id == chat_id)
                    .limit(1)
                )
                result = await session.execute(stmt)
                return result.scalar_one_or_none()
            else:
                # В multi-mode нужен topic_id, возвращаем None
                return None

    async def get_topic_id_from_message(self, message) -> int | None:
        """Получить topic_id из сообщения"""
        try:
            # Проверяем, есть ли topic_id в сообщении
            if hasattr(message, "message_thread_id") and message.message_thread_id:
                return message.message_thread_id
            return None
        except Exception as e:
            logger.error(f"Ошибка получения topic_id из сообщения: {e}")
            return None

    async def update_chat_settings(
        self,
        chat_id: int,
        user_id: int,
        bot: Bot,
        topic_id: int | None = None,
        reminder1_offset: int | None = None,
        reminder1_unit: str | None = None,
        reminder2_offset: int | None = None,
        reminder2_unit: str | None = None,
        topic_title: str | None = None,
        *,
        topic_id_set: bool = False,
    ) -> tuple[bool, str]:
        """Обновить настройки уведомлений чата/топика"""
        async with db_manager.async_session() as session:
            try:
                # Получаем чат в текущей сессии
                chat = await session.get(Chat, chat_id)
                if not chat:
                    return False, "Чат не настроен"

                # Получаем топик в текущей сессии с учетом режима
                if chat.mode == "single":
                    # В single-mode игнорируем topic_id и получаем единственный топик
                    stmt = select(ChatTopic).where(ChatTopic.chat_id == chat_id)
                    result = await session.execute(stmt)
                    topics = list(result.scalars().all())
                    if not topics:
                        return False, "Топик не найден"
                    if len(topics) > 1:
                        return False, "В single-mode должен быть только один топик"
                    chat_topic = topics[0]
                else:
                    # В multi-mode используем topic_id
                    stmt = (
                        select(ChatTopic)
                        .where(
                            and_(
                                ChatTopic.chat_id == chat_id,
                                ChatTopic.topic_id == topic_id if topic_id is not None else ChatTopic.topic_id.is_(None)
                            )
                        )
                    )
                    result = await session.execute(stmt)
                    chat_topic = result.scalar_one_or_none()

                    if not chat_topic:
                        return False, "Топик не найден"

                # Проверяем права админа
                if not await self.is_chat_admin(bot, chat_id, user_id):
                    return False, "У вас нет прав для изменения настроек"

                # Вычисляем финальные значения
                final_reminder1_offset = reminder1_offset if reminder1_offset is not None else chat_topic.reminder1_offset
                final_reminder1_unit = reminder1_unit if reminder1_unit is not None else chat_topic.reminder1_unit
                final_reminder2_offset = reminder2_offset if reminder2_offset is not None else chat_topic.reminder2_offset
                final_reminder2_unit = reminder2_unit if reminder2_unit is not None else chat_topic.reminder2_unit

                # Проверяем, что первое и второе уведомления не настроены одинаково
                if (
                    final_reminder1_offset == final_reminder2_offset
                    and final_reminder1_unit == final_reminder2_unit
                ):
                    return (
                        False,
                        "Первое и второе уведомления не могут быть настроены одинаково",
                    )

                # Обновляем настройки
                if reminder1_offset is not None:
                    chat_topic.reminder1_offset = reminder1_offset
                if reminder1_unit is not None:
                    chat_topic.reminder1_unit = reminder1_unit
                if reminder2_offset is not None:
                    chat_topic.reminder2_offset = reminder2_offset
                if reminder2_unit is not None:
                    chat_topic.reminder2_unit = reminder2_unit
                # Явное изменение топика (включая установку на общий чат = None)
                if topic_id_set:
                    chat_topic.topic_id = topic_id
                    chat_topic.topic_title = topic_title if topic_id is not None else None

                # Обновляем название чата, если оно изменилось
                try:
                    chat_info = await bot.get_chat(chat_id)
                    new_chat_title = getattr(chat_info, "title", None)
                    if new_chat_title and new_chat_title != chat.chat_title:
                        chat.chat_title = new_chat_title
                except Exception as e:
                    logger.debug(f"Не удалось обновить chat_title для чата {chat_id}: {e}")

                await session.commit()

                # Если изменился topic_id, перепланируем уведомления
                if topic_id_set:
                    from src.bot.services.chat_notification_scheduler_service import (
                        chat_notification_scheduler_service,
                    )
                    await chat_notification_scheduler_service.reschedule_notifications_for_chat_settings_update(chat_topic)

                return True, "Настройки успешно обновлены"

            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка обновления настроек чата {chat_id}: {e}")
                return False, "Произошла ошибка при обновлении настроек"

    async def toggle_chat_active(self, chat_id: int, user_id: int, bot: Bot, topic_id: int | None = None) -> tuple[bool, str]:
        """Переключить активность уведомлений в чате/топике"""
        async with db_manager.async_session() as session:
            try:
                # Получаем чат для определения режима
                chat = await session.get(Chat, chat_id)
                if not chat:
                    return False, "❌ Чат не найден"

                # Получаем топик в текущей сессии с учетом режима
                if chat.mode == "single":
                    # В single-mode игнорируем topic_id и получаем единственный топик
                    stmt = (
                        select(ChatTopic)
                        .where(ChatTopic.chat_id == chat_id)
                    )
                    result = await session.execute(stmt)
                    topics = list(result.scalars().all())
                    if not topics:
                        return False, "❌ Топик не найден"
                    if len(topics) > 1:
                        return False, "❌ В single-mode должен быть только один топик"
                    chat_topic = topics[0]
                else:
                    # В multi-mode используем topic_id
                    stmt = (
                        select(ChatTopic)
                        .where(
                            and_(
                                ChatTopic.chat_id == chat_id,
                                ChatTopic.topic_id == topic_id if topic_id is not None else ChatTopic.topic_id.is_(None)
                            )
                        )
                    )
                    result = await session.execute(stmt)
                    chat_topic = result.scalar_one_or_none()

                    if not chat_topic:
                        return False, "❌ Топик не найден"

                # Проверяем права админа
                if not await self.is_chat_admin(bot, chat_id, user_id):
                    return False, "У вас нет прав для изменения настроек"

                # Сохраняем старое значение для сообщения

                # Переключаем активность
                chat_topic.is_active = not chat_topic.is_active
                await session.commit()

                status = "включены" if chat_topic.is_active else "отключены"
                return True, f"✅ Уведомления {status}"

            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка переключения активности чата {chat_id}: {e}")
                return False, "Произошла ошибка при изменении настроек"

    async def get_all_chat_groups(self) -> list[dict]:
        """Получить все настроенные чаты с объединенными данными"""
        async with db_manager.async_session() as session:
            try:
                stmt = select(Chat).options(selectinload(Chat.topics).selectinload(ChatTopic.subject))
                result = await session.execute(stmt)
                chats = list(result.scalars().all())

                # Формируем объединенные данные
                result_list = []
                for chat in chats:
                    for topic in chat.topics:
                        result_list.append({
                            "chat": chat,
                            "topic": topic,
                            "subject": topic.subject,
                        })
                return result_list
            except Exception as e:
                logger.error(f"Ошибка получения списка чатов: {e}")
                return []

    async def get_chat_groups_topics(self, chat_id: int) -> list[ChatTopic]:
        """Получить все топики чата"""
        async with db_manager.async_session() as session:
            try:
                stmt = (
                    select(ChatTopic)
                    .options(selectinload(ChatTopic.subject))
                    .where(ChatTopic.chat_id == chat_id)
                    .order_by(ChatTopic.created_at)
                )
                result = await session.execute(stmt)
                return list(result.scalars().all())
            except Exception as e:
                logger.error(f"Ошибка получения топиков чата {chat_id}: {e}")
                return []

    async def get_chats_count(self) -> int:
        """Получить количество настроенных чатов"""
        async with db_manager.async_session() as session:
            try:
                stmt = select(Chat)
                result = await session.execute(stmt)
                return len(result.scalars().all())
            except Exception as e:
                logger.error(f"Ошибка подсчета чатов: {e}")
                return 0

    async def get_topics_count(self) -> int:
        """Получить количество настроенных топиков"""
        async with db_manager.async_session() as session:
            try:
                stmt = select(ChatTopic)
                result = await session.execute(stmt)
                return len(result.scalars().all())
            except Exception as e:
                logger.error(f"Ошибка подсчета топиков: {e}")
                return 0

    async def get_chat_groups_count(self) -> int:
        """Получить количество настроенных чатов (обратная совместимость)"""
        return await self.get_chats_count()

    async def get_active_chat_groups_count(self) -> int:
        """Получить количество активных топиков"""
        async with db_manager.async_session() as session:
            try:
                stmt = select(ChatTopic).where(ChatTopic.is_active)
                result = await session.execute(stmt)
                return len(result.scalars().all())
            except Exception as e:
                logger.error(f"Ошибка подсчета активных топиков: {e}")
                return 0


    async def change_chat_subject(self, bot: Bot, chat_id: int, new_subject_id: int, user_id: int, topic_id: int | None = None) -> tuple[bool, str]:
        """Смена дисциплины чата/топика"""
        try:
            async with db_manager.async_session() as session:
                # Получаем чат для определения режима
                chat = await session.get(Chat, chat_id)
                if not chat:
                    return False, "❌ Чат не найден"

                # Получаем топик в текущей сессии с учетом режима
                if chat.mode == "single":
                    # В single-mode игнорируем topic_id и получаем единственный топик
                    stmt = (
                        select(ChatTopic)
                        .options(selectinload(ChatTopic.subject))
                        .where(ChatTopic.chat_id == chat_id)
                    )
                    result = await session.execute(stmt)
                    topics = list(result.scalars().all())
                    if not topics:
                        return False, "❌ Топик не найден"
                    if len(topics) > 1:
                        return False, "❌ В single-mode должен быть только один топик"
                    chat_topic = topics[0]
                else:
                    # В multi-mode используем topic_id
                    stmt = (
                        select(ChatTopic)
                        .options(selectinload(ChatTopic.subject))
                        .where(
                            and_(
                                ChatTopic.chat_id == chat_id,
                                ChatTopic.topic_id == topic_id if topic_id is not None else ChatTopic.topic_id.is_(None)
                            )
                        )
                    )
                    result = await session.execute(stmt)
                    chat_topic = result.scalar_one_or_none()

                    if not chat_topic:
                        return False, "❌ Топик не найден"

                # Проверяем права доступа
                if not await self.is_chat_admin(bot, chat_id, user_id):
                    return False, "❌ У вас нет прав для изменения дисциплины чата"

                # Получаем новую дисциплину
                new_subject = await session.get(Subject, new_subject_id)
                if not new_subject:
                    return False, "❌ Дисциплина не найдена"

                # Сохраняем старое название для лога
                old_subject_name = chat_topic.subject.name if chat_topic.subject else "—"

                # Обновляем дисциплину
                chat_topic.subject_id = new_subject_id

                await session.commit()

                # Обновляем relationship для получения нового названия
                await session.refresh(chat_topic, ["subject"])

                logger.info(
                    f"Дисциплина чата {chat_id} (топик {topic_id}) изменена с '{old_subject_name}' на '{new_subject.name}'"
                )

                return True, f"✅ Дисциплина изменена с '{old_subject_name}' на '{new_subject.name}'"

        except Exception as e:
            logger.error(f"Ошибка смены дисциплины чата {chat_id}: {e}")
            return False, "❌ Произошла ошибка при смене дисциплины"


    async def update_chat_title(self, chat_id: int, chat_title: str | None) -> bool:
        """Обновить название чата"""
        try:
            async with db_manager.async_session() as session:
                chat = await session.get(Chat, chat_id)
                if chat:
                    chat.chat_title = chat_title
                    await session.commit()
                    logger.debug(f"Название чата {chat_id} обновлено: {chat_title}")
                    return True
                return False
        except Exception as e:
            logger.error(f"Ошибка обновления названия чата {chat_id}: {e}")
            return False

    async def deactivate_chat(self, chat_id: int) -> bool:
        """Деактивация всех топиков чата (при удалении бота)"""
        try:
            async with db_manager.async_session() as session:
                stmt = select(ChatTopic).where(ChatTopic.chat_id == chat_id)
                result = await session.execute(stmt)
                topics = list(result.scalars().all())

                for topic in topics:
                    topic.is_active = False

                await session.commit()
                logger.info(f"Чат {chat_id} деактивирован ({len(topics)} топиков)")
                return True
        except Exception as e:
            logger.error(f"Ошибка деактивации чата {chat_id}: {e}")
            return False

    async def activate_chat(self, chat_id: int, bot: Bot | None = None) -> bool:
        """Активация всех топиков чата (при повторном добавлении бота)"""
        try:
            async with db_manager.async_session() as session:
                stmt = select(ChatTopic).where(ChatTopic.chat_id == chat_id)
                result = await session.execute(stmt)
                topics = list(result.scalars().all())

                for topic in topics:
                    topic.is_active = True

                # Обновляем название чата, если есть доступ к боту
                if bot:
                    try:
                        chat_info = await bot.get_chat(chat_id)
                        chat_title = getattr(chat_info, "title", None)
                        if chat_title:
                            chat = await session.get(Chat, chat_id)
                            if chat:
                                chat.chat_title = chat_title
                    except Exception as e:
                        logger.warning(f"Не удалось обновить chat_title для чата {chat_id}: {e}")

                await session.commit()
                logger.info(f"Чат {chat_id} активирован ({len(topics)} топиков)")
                return True
        except Exception as e:
            logger.error(f"Ошибка активации чата {chat_id}: {e}")
            return False

    async def switch_chat_mode(self, chat_id: int, new_mode: str, user_id: int, bot: Bot) -> tuple[bool, str]:
        """Переключить режим чата (single ↔ multi)"""
        try:
            async with db_manager.async_session() as session:
                # Получаем чат в текущей сессии
                chat = await session.get(Chat, chat_id)
                if not chat:
                    return False, "❌ Чат не найден"

                # Проверяем права админа
                if not await self.is_chat_admin(bot, chat_id, user_id):
                    return False, "❌ У вас нет прав для изменения режима чата"

                if chat.mode == new_mode:
                    return False, f"❌ Чат уже в режиме {new_mode}"

                # Получаем все топики
                stmt = select(ChatTopic).where(ChatTopic.chat_id == chat_id)
                result = await session.execute(stmt)
                topics = list(result.scalars().all())

                # Удаляем все топики и их уведомления при переключении режима
                if topics:
                    # Удаляем все топики (они будут удалены каскадно вместе с уведомлениями)
                    for topic in topics:
                        await session.delete(topic)

                # Переключаем режим
                chat.mode = new_mode
                await session.commit()

                mode_name = "single" if new_mode == "single" else "multi"
                if topics:
                    return True, f"✅ Режим изменен на {mode_name}. Все настройки топиков удалены. Настройте чат заново."
                else:
                    return True, f"✅ Режим изменен на {mode_name}. Настройте чат заново."

        except Exception as e:
            logger.error(f"Ошибка переключения режима чата {chat_id}: {e}")
            return False, "❌ Произошла ошибка при переключении режима"


# Создаем экземпляр сервиса
chat_service = ChatService()
