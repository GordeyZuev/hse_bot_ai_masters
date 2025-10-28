"""
Обработчики для групповых чатов и топиков.

Этот модуль содержит всю логику для работы с групповыми чатами:
- Настройка бота на предметы
- Управление настройками уведомлений
- Интерфейс для команды /start в чатах
- Callback обработчики для интерактивных кнопок
"""

from aiogram import F, Router
from aiogram.filters import Command, and_f
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from src.bot.services.chat_notification_scheduler_service import (
    chat_notification_scheduler_service,
)
from src.bot.services.chat_service import chat_service
from src.core.database import db_manager
from src.core.models import Subject
from src.utils import get_logger


logger = get_logger()
router = Router()
# Утилита безопасной отправки сообщения: если топик закрыт, шлем в общий чат
async def _safe_send(message: Message, text: str, reply_markup=None, edit: bool = False):
    try:
        if edit:
            return await message.edit_text(text.strip(), reply_markup=reply_markup, parse_mode="HTML")
        return await message.answer(text.strip(), reply_markup=reply_markup, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "TOPIC_CLOSED" in str(e):
            # Падение из-за закрытого топика – отправляем в общий чат без thread_id
            return await message.bot.send_message(
                chat_id=message.chat.id,
                text=text.strip(),
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        raise

# Унифицированное получение отображаемого названия топика
async def _resolve_topic_title(message: Message, chat_id: int, topic_id: int | None) -> str | None:
    """Вернуть название темы (при наличии) по данным сообщения/чата.

    1) Пытаемся взять message.reply_to_message.forum_topic_created.name|title
    2) Если нет — пробуем через Bot API (chat_service.get_topic_title)
    3) Если не удалось — None
    """
    try:
        rtc = getattr(message, "reply_to_message", None)
        ftc = getattr(rtc, "forum_topic_created", None) if rtc else None
        if ftc:
            title_from_message = getattr(ftc, "name", None) or getattr(ftc, "title", None)
            if title_from_message:
                return title_from_message
    except Exception:
        pass

    try:
        if topic_id:
            return await chat_service.get_topic_title(message.bot, chat_id, topic_id)
    except Exception:
        pass

    return None

@router.callback_query(F.data == "chat_set_topic_here")
async def callback_chat_set_topic_here(callback: CallbackQuery, db_user):
    """Привязать чат к текущему топику (если команда вызвана из топика)"""
    await callback.answer()

    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id

        # Определяем topic_id из сообщения (None = общий чат)
        topic_id = await chat_service.get_topic_id_from_message(callback.message)

        # Пытаемся определить название текущего топика для кеша
        topic_title = None
        if topic_id is not None:
            # 1) из контекста сообщения
            topic_title = await _resolve_topic_title(callback.message, chat_id, topic_id)
            # 2) если не нашли — через API
            if not topic_title:
                try:
                    topic_title = await chat_service.get_topic_title(callback.bot, chat_id, topic_id)
                except Exception:
                    topic_title = None

        success, msg = await chat_service.update_chat_settings(
            chat_id=chat_id,
            user_id=user_id,
            bot=callback.bot,
            topic_id=topic_id,
            topic_title=topic_title,
            topic_id_set=True,
        )

        if success:
            # Показываем подтверждение и кнопку «Назад (в настройки)»
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            builder = InlineKeyboardBuilder()
            builder.button(text="🔙 Назад (в настройки)", callback_data="chat_settings_from_start")
            builder.adjust(1)

            bound_label = (
                "Общий чат" if topic_id is None else (topic_title or f"ID {topic_id}")
            )
            confirm_text = f"✅ Топик привязан: <b>«{bound_label}»</b>"

            try:
                await callback.message.edit_text(
                    confirm_text,
                    reply_markup=builder.as_markup(),
                    parse_mode="HTML",
                )
            except TelegramBadRequest as e:
                err = str(e)
                if "message is not modified" in err:
                    pass
                elif "TOPIC_CLOSED" in err:
                    await callback.bot.send_message(
                        chat_id=chat_id,
                        text=confirm_text,
                        reply_markup=builder.as_markup(),
                        parse_mode="HTML",
                    )
                else:
                    raise
        else:
            await callback.message.answer(f"❌ {msg}")

    except Exception as e:
        logger.error(f"Ошибка привязки топика: {e}")
        await callback.message.answer("Произошла ошибка при привязке топика")





# ============================================================================
# FSM СОСТОЯНИЯ
# ============================================================================

class ChatSetupStates(StatesGroup):
    """Состояния для процесса настройки бота"""
    waiting_subject_selection = State()
    waiting_time_settings = State()
    waiting_reminder1_selection = State()
    waiting_reminder2_selection = State()


class ChatSettingsStates(StatesGroup):
    """Состояния для редактирования настроек бота"""
    waiting_reminder1_offset = State()
    waiting_reminder1_unit = State()
    waiting_reminder2_offset = State()
    waiting_reminder2_unit = State()


# ============================================================================
# СПРАВКА ДЛЯ ЧАТОВ
# ============================================================================

async def send_chat_help_message(message: Message, edit_mode: bool = False):
    """Отправка сообщения со справкой для групповых чатов"""
    try:

        text = """
🤖 <b>Справка для группового чата</b>

Бот помогает отслеживать дедлайны по предметам прямо в чате.

Управляйте через кнопки — так удобнее.

<b>Как настроить:</b>
1) Убедитесь, что вы администратор чата
2) Перейдите в топик, в котором хотите отслеживать дедлайны (Можно изменить позже в настройках бота)
3) Нажмите «Настройка бота» и выберите предмет
4) При желании, можно изменить стандартные настройки уведомлений


<b>Важно:</b> для закрытых тем у бота должно быть право админа «Управление темами».

<b>Команды (при необходимости):</b>
<blockquote expandable>
• /start — краткое приветствие и ссылки
• /setup_discipline — выбрать предмет и привязать бота (только для админов)
• /disable_chat — включить/выключить уведомления в чате (для админов)
• /help — эта справка
</blockquote>
        """

        builder = InlineKeyboardBuilder()
        # Кнопка настройки бота показывается только если бот уже настроен в этом чате
        try:
            chat_id = message.chat.id
            chat_group = await chat_service.get_chat_group(chat_id)
        except Exception:
            chat_group = None
        if chat_group:
            builder.button(text="⚙️ Настройка бота", callback_data="chat_settings_from_start")
        builder.button(text="🔙 Назад", callback_data="back_to_start")
        builder.adjust(1)

        if edit_mode:
            await message.edit_text(text.strip(), reply_markup=builder.as_markup(), parse_mode="HTML")
        else:
            await message.answer(text.strip(), reply_markup=builder.as_markup(), parse_mode="HTML")

    except Exception as e:
        logger.error(f"Ошибка отправки справки чата: {e}")
        if not edit_mode:
            await message.answer("Произошла ошибка при отправке справки")


async def show_chat_setup_interface(message: Message, edit_mode: bool = False):
    """Показать интерфейс настройки бота (когда еще не настроен)"""
    try:

        text = """
⚙️ <b>Настройка бота</b>

Выберите предмет для отслеживания дедлайнов в этом чате:
        """

        builder = InlineKeyboardBuilder()
        builder.button(text="⚙️ Настроить бота", callback_data="chat_setup_from_start")
        builder.button(text="🔙 Назад", callback_data="back_to_start")
        builder.adjust(1)

        if edit_mode:
            await message.edit_text(text.strip(), reply_markup=builder.as_markup(), parse_mode="HTML")
        else:
            await message.answer(text.strip(), reply_markup=builder.as_markup(), parse_mode="HTML")

    except Exception as e:
        logger.error(f"Ошибка показа интерфейса настройки бота: {e}")
        if not edit_mode:
            await message.answer("Произошла ошибка при настройке бота")


async def show_chat_settings_interface(message: Message, chat_group, edit_mode: bool = False):
    """Показать интерфейс управления настройками бота (когда бот настроен)"""
    try:
        chat_id = message.chat.id

        # Формируем информацию о настройках
        text = "⚙️ <b>Настройка бота</b>\n\n"

        # Приводим единицы времени к человекочитаемым
        def unit_label(u: str) -> str:
            return "дн." if u == "days" else ("ч." if u == "hours" else u)

        # Секция: Настройки (самое важное сверху)
        text += "<b>🧩 Настройки</b>:\n"
        text += f"• <b>Предмет:</b> «{chat_group.subject.name}»\n"
        if chat_group.topic_id:
            # В настройках сначала выводим сохранённое имя (если есть), затем пытаемся получить по API
            topic_title_saved = getattr(chat_group, "topic_title", None)
            topic_title_api = None if topic_title_saved else await chat_service.get_topic_title(message.bot, chat_id, chat_group.topic_id)
            topic_display = (topic_title_saved or topic_title_api) or f"ID {chat_group.topic_id}"
            text += f"• <b>Топик:</b> «{topic_display}»\n"
        else:
            text += "• <b>Топик:</b> Общий чат\n"
        try:
            can_manage_topics = await chat_service.bot_can_manage_topics(message.bot, chat_id)
            status_topics = "✅ есть" if can_manage_topics else "❌ нет"
            text += f"• <b>Управление темами:</b> {status_topics}\n"
        except Exception:
            text += "• <b>Управление темами:</b> —\n"
        text += f"• <b>Статус:</b> {'✅ Включен' if chat_group.is_active else '❌ Выключен'}\n"

        # Секция: Уведомления
        text += "\n<b>🔔 Уведомления</b>:\n"
        text += (
            f"• <b>Первое:</b> за {chat_group.reminder1_offset} {unit_label(chat_group.reminder1_unit)}\n"
        )
        text += (
            f"• <b>Второе:</b> за {chat_group.reminder2_offset} {unit_label(chat_group.reminder2_unit)}\n"
        )

        # Секция: Статистика
        text += "\n<b>📊 Статистика</b>:\n"

        # Добавляем статистику уведомлений
        try:
            async with db_manager.async_session() as session:
                from sqlalchemy import func, select

                from src.core.models.models import ChatScheduledNotification

                # Подсчитываем общее количество уведомлений
                total_result = await session.execute(
                    select(func.count(ChatScheduledNotification.id)).where(
                        ChatScheduledNotification.chat_group_id == chat_id
                    )
                )
                total_notifications = total_result.scalar() or 0

                # Подсчитываем запланированные уведомления
                scheduled_result = await session.execute(
                    select(func.count(ChatScheduledNotification.id)).where(
                        ChatScheduledNotification.chat_group_id == chat_id,
                        ChatScheduledNotification.status == "scheduled"
                    )
                )
                scheduled_notifications = scheduled_result.scalar() or 0

                text += f"• Всего уведомлений: {total_notifications}\n"
                text += f"• Запланировано: {scheduled_notifications}\n"

        except Exception as e:
            logger.error(f"Ошибка получения статистики уведомлений для чата {chat_id}: {e}")

        # Убираем вывод даты создания по ТЗ

        builder = InlineKeyboardBuilder()
        builder.button(text="📚 Изменить дисциплину", callback_data="chat_change_subject")
        builder.button(text="⚙️ Настроить уведомления", callback_data="chat_edit_settings")
        # Добавляем переключатель уведомлений в общий раздел
        if chat_group.is_active:
            builder.button(text="🔕 Выключить уведомления", callback_data="chat_toggle_active")
        else:
            builder.button(text="🔔 Включить уведомления", callback_data="chat_toggle_active")

        # Управление топиком
        builder.button(text="📍 Привязать к этому топику", callback_data="chat_set_topic_here")

        builder.button(text="🔙 Назад", callback_data="back_to_start")
        builder.adjust(1)

        if edit_mode:
            try:
                await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
            except TelegramBadRequest as e:
                err = str(e)
                # Если содержимое такое же, просто ничего не делаем
                if "message is not modified" in err:
                    return
                # Если тема закрыта — отправляем новое сообщение в общий чат
                if "TOPIC_CLOSED" in err:
                    await message.bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        reply_markup=builder.as_markup(),
                        parse_mode="HTML",
                    )
                else:
                    raise
        else:
            await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")

    except Exception as e:
        logger.error(f"Ошибка показа интерфейса настроек бота: {e}")
        if not edit_mode:
            await message.answer("Произошла ошибка при получении настроек бота")


# ============================================================================
# ОСНОВНЫЕ КОМАНДЫ ЧАТОВ
# ============================================================================

async def handle_start_in_group(message: Message, db_user, user_name: str):
    """Обработка команды /start в групповом чате"""
    try:
        chat_id = message.chat.id
        user_id = message.from_user.id
        chat_title = message.chat.title or f"Чат {chat_id}"
        username = message.from_user.username

        logger.info(f"[CHAT] /start в чате '{chat_title}' (ID: {chat_id}) пользователем @{username or f'ID{user_id}'}")

        # Проверяем, настроен ли уже чат
        chat_group = await chat_service.get_chat_group(chat_id)

        if chat_group:
            # Чат уже настроен — краткое приветствие и ссылка на помощь
            text = f"""
🤖 <b>Привет!</b>

Бот уже настроен на предмет: <b>«{chat_group.subject.name}»</b>
Статус: {'✅ Активен' if chat_group.is_active else '❌ Отключен'}

<i>Все о настройке и возможностях — в разделе помощи.</i>
            """

            builder = InlineKeyboardBuilder()
            builder.button(text="⚙️ Настройка бота", callback_data="chat_settings_from_start")
            builder.button(text="ℹ️ Помощь", callback_data="quick_help")
            builder.adjust(1)

        else:
            # Чат не настроен — краткое приветствие и ссылка на помощь
            text = """
🤖 <b>Привет!</b>

Этот бот помогает отслеживать дедлайны по предметам в этом чате.

<b>Как начать:</b>
1) Убедитесь, что вы администратор чата
2) Нажмите «Настроить бота» ниже
3) Выберите предмет для отслеживания дедлайнов

<b>Совет:</b> Настраивайте бота в нужном топике — тогда напоминания будут приходить только туда.

Подробные инструкции — в разделе помощи.
            """

            builder = InlineKeyboardBuilder()
            builder.button(text="⚙️ Настроить бота", callback_data="chat_setup_from_start")
            builder.button(text="ℹ️ Помощь", callback_data="quick_help")
            builder.adjust(1)

        try:
            await message.answer(text.strip(), reply_markup=builder.as_markup())
        except TelegramBadRequest as e:
            if "TOPIC_CLOSED" in str(e):
                topic_id = getattr(message, "message_thread_id", None)
                topic_title = await _resolve_topic_title(message, chat_id, topic_id)
                topic_label = topic_title or (f"ID {topic_id}" if topic_id else "")
                notice = (
                    f"<b>⚠️ Топик «{topic_label}» закрыт.</b>\n\n"
                    "Боту нужно право «Управление темами»\n"
                    "Выдайте право или вызовите бота в открытом топике."
                )
                await message.bot.send_message(chat_id=chat_id, text=notice, parse_mode="HTML")
                return
            raise

    except Exception as e:
        logger.error(f"Ошибка обработки /start в группе: {e}")
        try:
            await message.answer("Произошла ошибка при настройке бота.")
        except TelegramBadRequest as e2:
            if "TOPIC_CLOSED" in str(e2):
                topic_id = getattr(message, "message_thread_id", None)
                topic_title = await _resolve_topic_title(message, message.chat.id, topic_id)
                topic_label = topic_title or (f"ID {topic_id}" if topic_id else "")
                notice = (
                    f"<b>⚠️ Топик «{topic_label}» закрыт.</b>\n\n"
                    "Боту нужно право «Управление темами»\n"
                    "Выдайте право или вызовите бота в открытом топике."
                )
                await message.bot.send_message(chat_id=message.chat.id, text=notice, parse_mode="HTML")
            else:
                raise


@router.message(and_f(Command("help"), F.chat.type.in_(["group", "supergroup"])))
async def cmd_chat_help(message: Message, db_user):
    """Команда справки для групповых чатов"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    chat_title = message.chat.title or f"Чат {chat_id}"
    username = message.from_user.username

    logger.info(f"[CHAT] /help в чате '{chat_title}' (ID: {chat_id}) пользователем @{username or f'ID{user_id}'}")

    await send_chat_help_message(message)


@router.message(and_f(Command("setup_discipline"), F.chat.type.in_(["group", "supergroup"])))
async def cmd_setup_discipline(message: Message, db_user, state: FSMContext):
    """Команда настройки чата на предмет"""

    chat_id = message.chat.id
    user_id = message.from_user.id
    chat_title = message.chat.title or f"Чат {chat_id}"
    username = message.from_user.username

    logger.info(f"[CHAT] /setup_discipline в чате '{chat_title}' (ID: {chat_id}) пользователем @{username or f'ID{user_id}'}")

    try:
        # Проверяем, не настроен ли уже чат
        existing_chat = await chat_service.get_chat_group(chat_id)
        if existing_chat:
            subject_name = existing_chat.subject.name
            topic_info = f" (топик {existing_chat.topic_id})" if existing_chat.topic_id else " (общий чат)"
            await message.answer(
                f"ℹ️ Этот чат уже настроен на предмет: <b>«{subject_name}»</b>{topic_info}\n\n"
                f"Используйте /chat_settings для изменения настроек",
                parse_mode="HTML"
            )
            return

        # Получаем список доступных предметов
        async with db_manager.async_session() as session:
            from sqlalchemy import select
            stmt = select(Subject).where(Subject.is_active).order_by(Subject.name)
            result = await session.execute(stmt)
            subjects = list(result.scalars().all())

        if not subjects:
            await message.answer("❌ Нет доступных предметов для настройки")
            return

        # Показываем список предметов
        text = "📚 <b>Выберите предмет для чата:</b>\n\n"

        builder = InlineKeyboardBuilder()
        for subject in subjects:
            builder.button(
                text=f"📖 {subject.name}",
                callback_data=f"chat_setup_subject_{subject.id}"
            )

        builder.button(text="❌ Отмена", callback_data="chat_setup_cancel")
        builder.adjust(1)

        await state.set_state(ChatSetupStates.waiting_subject_selection)
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")

    except Exception as e:
        logger.error(f"Ошибка в команде setup_discipline: {e}")
        await message.answer("Произошла ошибка при настройке бота")


@router.message(and_f(Command("chat_settings"), F.chat.type.in_(["group", "supergroup"])))
async def cmd_chat_settings(message: Message, db_user):
    """Команда показа настроек бота"""

    chat_id = message.chat.id
    user_id = message.from_user.id
    chat_title = message.chat.title or f"Чат {chat_id}"
    username = message.from_user.username

    logger.info(f"[CHAT] /chat_settings в чате '{chat_title}' (ID: {chat_id}) пользователем @{username or f'ID{user_id}'}")

    try:
        # Проверяем права доступа
        if not await chat_service.is_chat_admin(message.bot, chat_id, user_id):
            await message.answer("❌ Управлять ботом могут только администраторы чата")
            return

        chat_group = await chat_service.get_chat_group(chat_id)

        if not chat_group:
            # Чат не настроен - показываем интерфейс настройки
            await show_chat_setup_interface(message)
        else:
            # Чат настроен - показываем интерфейс управления настройками
            await show_chat_settings_interface(message, chat_group)

    except Exception as e:
        logger.error(f"Ошибка в команде chat_settings: {e}")
        await message.answer("Произошла ошибка при получении настроек бота")


@router.message(and_f(Command("disable_chat"), F.chat.type.in_(["group", "supergroup"])))
async def cmd_disable_chat(message: Message, db_user):
    """Команда отключения уведомлений в чате"""

    chat_id = message.chat.id
    user_id = message.from_user.id
    chat_title = message.chat.title or f"Чат {chat_id}"
    username = message.from_user.username

    logger.info(f"[CHAT] /disable_chat в чате '{chat_title}' (ID: {chat_id}) пользователем @{username or f'ID{user_id}'}")

    try:
        success, message_text = await chat_service.toggle_chat_active(chat_id, user_id, message.bot)
        await message.answer(message_text)

    except Exception as e:
        logger.error(f"Ошибка в команде disable_chat: {e}")
        await message.answer("Произошла ошибка при отключении бота")


# ============================================================================
# CALLBACK ОБРАБОТЧИКИ ДЛЯ НАСТРОЙКИ ЧАТА
# ============================================================================

@router.callback_query(F.data.startswith("chat_setup_subject_"))
async def callback_setup_chat_subject(callback: CallbackQuery, db_user, state: FSMContext):
    """Обработчик выбора предмета для настройки бота"""
    await callback.answer()

    try:
        subject_id = int(callback.data.split("_")[-1])
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        chat_title = callback.message.chat.title or f"Чат {chat_id}"
        username = callback.from_user.username

        logger.info(f"[CHAT] setup_chat_subject_{subject_id} в чате '{chat_title}' (ID: {chat_id}) пользователем @{username or f'ID{user_id}'}")

        # Получаем topic_id если команда вызвана в топике
        topic_id = await chat_service.get_topic_id_from_message(callback.message)

        # Создаем чат с дефолтными настройками и сразу переводим в раздел настроек
        success, message_text = await chat_service.setup_chat_group(
            callback.bot,
            chat_id,
            subject_id,
            user_id,
            topic_id,
            reminder1_offset=7,
            reminder1_unit="days",
            reminder2_offset=1,
            reminder2_unit="days",
            is_active=False,
        )

        if success:
            chat_group = await chat_service.get_chat_group(chat_id)
            await show_chat_settings_interface(callback.message, chat_group, edit_mode=True)
        else:
            await callback.message.edit_text(message_text, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Ошибка в callback_setup_chat_subject: {e}")
        await callback.message.edit_text("Произошла ошибка при настройке бота")


@router.callback_query(F.data == "chat_setup_cancel")
async def callback_setup_chat_cancel(callback: CallbackQuery, db_user, state: FSMContext):
    """Отмена настройки бота: сразу возвращаем в главное меню"""
    await callback.answer()

    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        chat_title = callback.message.chat.title or f"Чат {chat_id}"
        username = callback.from_user.username

        logger.info(f"[CHAT] setup_cancel в чате '{chat_title}' (ID: {chat_id}) пользователем @{username or f'ID{user_id}'}")

        await state.clear()
        # Возврат к главному экрану (единая инструкция)
        await callback_back_to_start(callback, db_user)

    except Exception as e:
        logger.error(f"Ошибка в callback_setup_chat_cancel: {e}")
        await callback.message.edit_text("Произошла ошибка при отмене настройки")


@router.callback_query(F.data == "chat_setup_reminder1")
async def callback_setup_reminder1(callback: CallbackQuery, db_user, state: FSMContext):
    """Настройка первого напоминания"""
    await callback.answer()

    try:
        text = """
⚙️ <b>Настройка первого напоминания</b>

Выберите за сколько времени до дедлайна отправлять первое напоминание:
        """

        builder = InlineKeyboardBuilder()

        # Добавляем варианты дней
        for days in [1, 3, 7, 14, 30]:
            builder.button(
                text=f"{days} дней",
                callback_data=f"chat_setup_reminder1_{days}_days"
            )

        # Добавляем варианты часов
        for hours in [6, 12, 24]:
            builder.button(
                text=f"{hours} часов",
                callback_data=f"chat_setup_reminder1_{hours}_hours"
            )

        builder.button(text="🔙 Назад", callback_data="chat_setup_from_start")
        builder.adjust(2)

        await callback.message.edit_text(text.strip(), reply_markup=builder.as_markup(), parse_mode="HTML")
        await state.set_state(ChatSetupStates.waiting_reminder1_selection)

    except Exception as e:
        logger.error(f"Ошибка в callback_setup_reminder1: {e}")
        await callback.message.edit_text("Произошла ошибка при настройке напоминания")


@router.callback_query(F.data == "chat_setup_reminder2")
async def callback_setup_reminder2(callback: CallbackQuery, db_user, state: FSMContext):
    """Настройка второго напоминания"""
    await callback.answer()

    try:
        text = """
⚙️ <b>Настройка второго напоминания</b>

Выберите за сколько времени до дедлайна отправлять второе напоминание:
        """

        builder = InlineKeyboardBuilder()

        # Добавляем варианты дней
        for days in [1, 2, 3, 7]:
            builder.button(
                text=f"{days} дней",
                callback_data=f"chat_setup_reminder2_{days}_days"
            )

        # Добавляем варианты часов
        for hours in [6, 12, 24]:
            builder.button(
                text=f"{hours} часов",
                callback_data=f"chat_setup_reminder2_{hours}_hours"
            )

        builder.button(text="🔙 Назад", callback_data="chat_setup_from_start")
        builder.adjust(2)

        await callback.message.edit_text(text.strip(), reply_markup=builder.as_markup(), parse_mode="HTML")
        await state.set_state(ChatSetupStates.waiting_reminder2_selection)

    except Exception as e:
        logger.error(f"Ошибка в callback_setup_reminder2: {e}")
        await callback.message.edit_text("Произошла ошибка при настройке напоминания")


@router.callback_query(F.data == "chat_setup_finish")
async def callback_setup_finish(callback: CallbackQuery, db_user, state: FSMContext):
    """Завершение настройки бота"""
    await callback.answer()

    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        chat_title = callback.message.chat.title or f"Чат {chat_id}"
        username = callback.from_user.username

        logger.info(f"[CHAT] setup_finish в чате '{chat_title}' (ID: {chat_id}) пользователем @{username or f'ID{user_id}'}")

        # Получаем данные из состояния
        data = await state.get_data()
        subject_id = data.get("subject_id")
        topic_id = data.get("topic_id")
        reminder1_offset = data.get("reminder1_offset", 7)
        reminder1_unit = data.get("reminder1_unit", "days")
        reminder2_offset = data.get("reminder2_offset", 1)
        reminder2_unit = data.get("reminder2_unit", "days")

        if not subject_id:
            await callback.message.edit_text("❌ Ошибка: предмет не выбран")
            await state.clear()
            return

        # Настраиваем чат
        success, message_text = await chat_service.setup_chat_group(
            callback.bot, chat_id, subject_id, user_id, topic_id,
            reminder1_offset=reminder1_offset,
            reminder1_unit=reminder1_unit,
            reminder2_offset=reminder2_offset,
            reminder2_unit=reminder2_unit
        )

        if success:
            # Планируем уведомления для нового чата
            scheduled_count = await chat_notification_scheduler_service.schedule_notifications_for_chat_subscription(
                chat_id, subject_id
            )

            message_text += f"\n\n📅 Запланировано {scheduled_count} уведомлений"

            # Предлагаем удалить сообщение
            builder = InlineKeyboardBuilder()
            builder.button(text="🗑️ Удалить сообщение", callback_data="chat_delete_message")
            builder.button(text="🔙 Назад", callback_data="back_to_start")
            builder.adjust(1)

            await callback.message.edit_text(message_text, reply_markup=builder.as_markup(), parse_mode="HTML")
        else:
            await callback.message.edit_text(message_text, parse_mode="HTML")

        await state.clear()

    except Exception as e:
        logger.error(f"Ошибка в callback_setup_finish: {e}")
        await callback.message.edit_text("Произошла ошибка при завершении настройки")


@router.callback_query(F.data.startswith("chat_setup_reminder1_"))
async def callback_set_reminder1_value(callback: CallbackQuery, db_user, state: FSMContext):
    """Установка значения первого напоминания"""
    await callback.answer()

    try:
        # Парсим данные
        parts = callback.data.split("_")
        offset = int(parts[3])
        unit = parts[4]

        # Сохраняем в состоянии
        await state.update_data(reminder1_offset=offset, reminder1_unit=unit)

        # Возвращаемся к настройке времени
        data = await state.get_data()
        subject_id = data.get("subject_id")
        subject = await db_manager.get_subject_by_id(subject_id)

        text = f"""
⚙️ <b>Настройка времени уведомлений</b>

Выбран предмет: <b>«{subject.name}»</b>

Настройте время уведомлений о дедлайнах:
• Первое напоминание: за {offset} {unit}
        """

        builder = InlineKeyboardBuilder()
        builder.button(text="1️⃣ Первое напоминание", callback_data="chat_setup_reminder1")
        builder.button(text="2️⃣ Второе напоминание", callback_data="chat_setup_reminder2")
        builder.button(text="✅ Завершить настройку", callback_data="chat_setup_finish")
        builder.button(text="🔙 Назад", callback_data="chat_setup_from_start")
        builder.adjust(1)

        await callback.message.edit_text(text.strip(), reply_markup=builder.as_markup(), parse_mode="HTML")
        await state.set_state(ChatSetupStates.waiting_time_settings)

    except Exception as e:
        logger.error(f"Ошибка в callback_set_reminder1_value: {e}")
        await callback.message.edit_text("Произошла ошибка при настройке напоминания")


@router.callback_query(F.data.startswith("chat_setup_reminder2_"))
async def callback_set_reminder2_value(callback: CallbackQuery, db_user, state: FSMContext):
    """Установка значения второго напоминания"""
    await callback.answer()

    try:
        # Парсим данные
        parts = callback.data.split("_")
        offset = int(parts[3])
        unit = parts[4]

        # Сохраняем в состоянии
        await state.update_data(reminder2_offset=offset, reminder2_unit=unit)

        # Возвращаемся к настройке времени
        data = await state.get_data()
        subject_id = data.get("subject_id")
        subject = await db_manager.get_subject_by_id(subject_id)

        text = f"""
⚙️ <b>Настройка времени уведомлений</b>

Выбран предмет: <b>«{subject.name}»</b>

Настройте время уведомлений о дедлайнах:
• Второе напоминание: за {offset} {unit}
        """

        builder = InlineKeyboardBuilder()
        builder.button(text="1️⃣ Первое напоминание", callback_data="chat_setup_reminder1")
        builder.button(text="2️⃣ Второе напоминание", callback_data="chat_setup_reminder2")
        builder.button(text="✅ Завершить настройку", callback_data="chat_setup_finish")
        builder.button(text="🔙 Назад", callback_data="chat_setup_from_start")
        builder.adjust(1)

        await callback.message.edit_text(text.strip(), reply_markup=builder.as_markup(), parse_mode="HTML")
        await state.set_state(ChatSetupStates.waiting_time_settings)

    except Exception as e:
        logger.error(f"Ошибка в callback_set_reminder2_value: {e}")
        await callback.message.edit_text("Произошла ошибка при настройке напоминания")


@router.callback_query(F.data == "chat_delete_message")
async def callback_delete_message(callback: CallbackQuery, db_user):
    """Удаление сообщения после настройки"""
    await callback.answer()

    try:
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")
        await callback.message.edit_text("❌ Не удалось удалить сообщение")

@router.callback_query(F.data == "chat_setup_from_start")
async def callback_setup_from_start(callback: CallbackQuery, db_user, state: FSMContext):
    """Обработчик кнопки настройки бота из /start"""
    await callback.answer()

    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        chat_title = callback.message.chat.title or f"Чат {chat_id}"
        username = callback.from_user.username

        logger.info(f"[CHAT] setup_from_start в чате '{chat_title}' (ID: {chat_id}) пользователем @{username or f'ID{user_id}'}")

        # Проверяем права админа
        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            # Не изменяем сообщение, просто небольшая плашка
            await callback.answer("❌ Управлять ботом могут только администраторы", show_alert=False)
            return

        # Получаем список доступных предметов
        async with db_manager.async_session() as session:
            from sqlalchemy import select
            stmt = select(Subject).where(Subject.is_active).order_by(Subject.name)
            result = await session.execute(stmt)
            subjects = list(result.scalars().all())

        if not subjects:
            await callback.message.edit_text("❌ Нет доступных предметов для настройки")
            return

        # Показываем список предметов
        text = "📚 <b>Выберите предмет для настройки бота:</b>\n\n"

        builder = InlineKeyboardBuilder()
        for subject in subjects:
            builder.button(
                text=f"📖 {subject.name}",
                callback_data=f"chat_setup_subject_{subject.id}"
            )

        builder.button(text="❌ Отмена", callback_data="chat_setup_cancel")
        builder.adjust(1)

        await state.set_state(ChatSetupStates.waiting_subject_selection)
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

    except Exception as e:
        logger.error(f"Ошибка в callback_setup_from_start: {e}")
        await callback.message.edit_text("Произошла ошибка при настройке бота")


@router.callback_query(F.data == "chat_settings_from_start")
async def callback_settings_from_start(callback: CallbackQuery, db_user):
    """Обработчик кнопки настроек бота из /start"""
    await callback.answer()

    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        chat_title = callback.message.chat.title or f"Чат {chat_id}"
        username = callback.from_user.username

        logger.info(f"[CHAT] settings_from_start в чате '{chat_title}' (ID: {chat_id}) пользователем @{username or f'ID{user_id}'}")

        # Проверяем права доступа
        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.answer("❌ Управлять ботом могут только администраторы", show_alert=False)
            return

        chat_group = await chat_service.get_chat_group(chat_id)

        if not chat_group:
            # Чат не настроен - показываем интерфейс настройки
            await show_chat_setup_interface(callback.message, edit_mode=True)
        else:
            # Чат настроен - показываем интерфейс управления настройками
            await show_chat_settings_interface(callback.message, chat_group, edit_mode=True)

    except Exception as e:
        logger.error(f"Ошибка в callback_settings_from_start: {e}")
        await callback.message.edit_text("Произошла ошибка при получении настроек бота")


@router.callback_query(F.data == "back_to_start")
async def callback_back_to_start(callback: CallbackQuery, db_user):
    """Возврат к /start"""
    await callback.answer()

    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        chat_title = callback.message.chat.title or f"Чат {chat_id}"
        username = callback.from_user.username

        logger.info(f"[CHAT] back_to_start в чате '{chat_title}' (ID: {chat_id}) пользователем @{username or f'ID{user_id}'}")

        # Проверяем, настроен ли уже чат
        chat_group = await chat_service.get_chat_group(chat_id)

        if chat_group:
            # Чат уже настроен
            text = f"""
🤖 <b>Настройка бота в чате</b>

Чат уже настроен на предмет: <b>«{chat_group.subject.name}»</b>

Статус: {'✅ Активен' if chat_group.is_active else '❌ Отключен'}
            """

            builder = InlineKeyboardBuilder()
            builder.button(text="⚙️ Настройка бота", callback_data="chat_settings_from_start")
            builder.button(text="ℹ️ Помощь", callback_data="quick_help")
            builder.adjust(1)

        else:
            # Чат не настроен — единая инструкция
            text = """
🤖 <b>Привет!</b>

Этот бот помогает отслеживать дедлайны по предметам в этом чате.

<b>Как начать:</b>
1) Убедитесь, что вы администратор чата
2) Нажмите «Настроить бота» ниже
3) Выберите предмет для отслеживания дедлайнов

<b>Совет:</b> Настраивайте бота в нужном топике — тогда напоминания будут приходить только туда.

Подробные инструкции — в разделе помощи.
            """

            builder = InlineKeyboardBuilder()
            builder.button(text="⚙️ Настроить бота", callback_data="chat_setup_from_start")
            builder.button(text="ℹ️ Помощь", callback_data="quick_help")
            builder.adjust(1)

        await callback.message.edit_text(text.strip(), reply_markup=builder.as_markup(), parse_mode="HTML")

    except Exception as e:
        logger.error(f"Ошибка в callback_back_to_start: {e}")
        await callback.message.edit_text("Произошла ошибка при возврате к главному меню")


@router.callback_query(F.data == "chat_change_subject")
async def callback_change_subject(callback: CallbackQuery, db_user, state: FSMContext):
    """Смена дисциплины чата"""
    await callback.answer()

    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        chat_title = callback.message.chat.title or f"Чат {chat_id}"
        username = callback.from_user.username

        logger.info(f"[CHAT] change_subject в чате '{chat_title}' (ID: {chat_id}) пользователем @{username or f'ID{user_id}'}")

        # Проверяем права доступа
        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.message.edit_text("❌ У вас нет прав для изменения дисциплины чата")
            return

        # Получаем список предметов
        subjects = await db_manager.get_all_subjects()

        text = """
📚 <b>Выбор дисциплины</b>

Выберите новую дисциплину для отслеживания дедлайнов:
        """

        builder = InlineKeyboardBuilder()

        for subject in subjects:
            builder.button(
                text=f"📖 {subject.name}",
                callback_data=f"chat_change_subject_{subject.id}"
            )

        builder.button(text="🔙 Назад", callback_data="chat_settings_from_start")
        builder.adjust(1)

        await callback.message.edit_text(text.strip(), reply_markup=builder.as_markup(), parse_mode="HTML")
        await state.set_state(ChatSetupStates.waiting_subject_selection)

    except Exception as e:
        logger.error(f"Ошибка в callback_change_subject: {e}")
        await callback.message.edit_text("Произошла ошибка при смене дисциплины")


@router.callback_query(F.data.startswith("chat_change_subject_"))
async def callback_change_subject_selected(callback: CallbackQuery, db_user, state: FSMContext):
    """Обработчик выбора новой дисциплины"""
    await callback.answer()

    try:
        subject_id = int(callback.data.split("_")[-1])
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        chat_title = callback.message.chat.title or f"Чат {chat_id}"
        username = callback.from_user.username

        logger.info(f"[CHAT] change_subject_{subject_id} в чате '{chat_title}' (ID: {chat_id}) пользователем @{username or f'ID{user_id}'}")

        # Получаем новую дисциплину
        await db_manager.get_subject_by_id(subject_id)

        # Обновляем дисциплину чата
        success, message_text = await chat_service.change_chat_subject(
            callback.bot, chat_id, subject_id, user_id
        )

        if success:
            # Перепланируем уведомления для новой дисциплины
            rescheduled_count = await chat_notification_scheduler_service.reschedule_notifications_for_chat_subject_change(
                chat_id, subject_id
            )

            message_text += f"\n\n🔄 Перепланировано {rescheduled_count} уведомлений"

            # Возвращаемся к интерфейсу настроек
            chat_group = await chat_service.get_chat_group(chat_id)
            await show_chat_settings_interface(callback.message, chat_group, edit_mode=True)
        else:
            await callback.message.edit_text(message_text, parse_mode="HTML")

        await state.clear()

    except Exception as e:
        logger.error(f"Ошибка в callback_change_subject_selected: {e}")
        await callback.message.edit_text("Произошла ошибка при смене дисциплины")

@router.callback_query(F.data == "chat_edit_settings")
async def callback_edit_chat_settings(callback: CallbackQuery, db_user):
    """Редактирование настроек бота"""
    await callback.answer()

    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id

        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.message.edit_text("❌ У вас нет прав для изменения настроек бота")
            return

        chat_group = await chat_service.get_chat_group(chat_id)
        if not chat_group:
            await callback.message.edit_text("❌ Чат не настроен")
            return

        text = "⚙️ <b>Настройка бота</b>\n\n"
        text += f"📚 <b>Предмет:</b> «{chat_group.subject.name}»\n\n"
        text += "🔔 <b>Текущие настройки:</b>\n"
        text += f"• Первое напоминание: за {chat_group.reminder1_offset} {chat_group.reminder1_unit}\n"
        text += f"• Второе напоминание: за {chat_group.reminder2_offset} {chat_group.reminder2_unit}\n\n"
        text += "Выберите, что хотите изменить:"

        builder = InlineKeyboardBuilder()
        builder.button(text="1️⃣ Первое напоминание", callback_data="chat_edit_reminder1")
        builder.button(text="2️⃣ Второе напоминание", callback_data="chat_edit_reminder2")
        # Переключатель уведомлений переносим из этого раздела в общий, поэтому удалён
        builder.button(text="🔙 Назад", callback_data="chat_settings_from_start")
        builder.adjust(1)

        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

    except Exception as e:
        logger.error(f"Ошибка в callback_edit_chat_settings: {e}")
        await callback.message.edit_text("Произошла ошибка при редактировании настроек")


@router.callback_query(F.data == "chat_edit_reminder1")
async def callback_edit_reminder1(callback: CallbackQuery, db_user):
    """Редактирование первого напоминания"""
    await callback.answer()

    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id

        # Проверяем права доступа
        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.message.edit_text("❌ У вас нет прав для изменения настроек бота")
            return

        chat_group = await chat_service.get_chat_group(chat_id)
        if not chat_group:
            await callback.message.edit_text("❌ Чат не настроен")
            return

        text = "1️⃣ <b>Первое напоминание</b>\n\n"
        text += f"Текущие настройки: за {chat_group.reminder1_offset} {chat_group.reminder1_unit}\n\n"
        text += "Выберите новое значение:"

        builder = InlineKeyboardBuilder()

        # Варианты для дней
        for days in [1, 3, 7, 14]:
            builder.button(
                text=f"{days} дней",
                callback_data=f"chat_set_reminder1_{days}_days"
            )

        # Варианты для часов
        for hours in [1, 6, 12, 24]:
            builder.button(
                text=f"{hours} часов",
                callback_data=f"chat_set_reminder1_{hours}_hours"
            )

        builder.button(text="🔙 Назад", callback_data="chat_settings_from_start")
        builder.adjust(2)

        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

    except Exception as e:
        logger.error(f"Ошибка в callback_edit_reminder1: {e}")
        await callback.message.edit_text("Произошла ошибка при редактировании настроек")


@router.callback_query(F.data.startswith("chat_set_reminder1_"))
async def callback_set_reminder1(callback: CallbackQuery, db_user):
    """Установка первого напоминания"""
    await callback.answer()

    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id

        # Парсим данные
        parts = callback.data.split("_")
        offset = int(parts[3])
        unit = parts[4]

        # Проверяем права доступа
        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.message.edit_text("❌ У вас нет прав для изменения настроек бота")
            return

        # Обновляем настройки
        success, message_text = await chat_service.update_chat_settings(
            chat_id, user_id, callback.bot,
            reminder1_offset=offset,
            reminder1_unit=unit
        )

        if success:
            # Перепланируем уведомления
            chat_group = await chat_service.get_chat_group(chat_id)
            rescheduled_count = await chat_notification_scheduler_service.reschedule_notifications_for_chat_settings_update(chat_group)

            message_text += f"\n\n🔄 Перепланировано {rescheduled_count} уведомлений"

            # Возвращаемся к интерфейсу настроек
            await show_chat_settings_interface(callback.message, chat_group, edit_mode=True)
        else:
            await callback.message.edit_text(message_text, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Ошибка в callback_set_reminder1: {e}")
        await callback.message.edit_text("Произошла ошибка при изменении настроек")


@router.callback_query(F.data == "chat_toggle_active")
async def callback_toggle_chat_active(callback: CallbackQuery, db_user):
    """Переключение активности бота"""
    await callback.answer()

    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        chat_title = callback.message.chat.title or f"Чат {chat_id}"
        username = callback.from_user.username

        logger.info(f"[CHAT] toggle_active в чате '{chat_title}' (ID: {chat_id}) пользователем @{username or f'ID{user_id}'}")

        # Проверяем права доступа
        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.message.edit_text("❌ У вас нет прав для изменения настроек бота")
            return

        # Переключаем активность
        success, message_text = await chat_service.toggle_chat_active(chat_id, user_id, callback.bot)

        if success:
            # Возвращаемся к интерфейсу настроек
            chat_group = await chat_service.get_chat_group(chat_id)
            await show_chat_settings_interface(callback.message, chat_group, edit_mode=True)
        else:
            await callback.message.edit_text(message_text, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Ошибка в callback_toggle_chat_active: {e}")
        await callback.message.edit_text("Произошла ошибка при изменении настроек")


# ============================================================================
# РЕГИСТРАЦИЯ HANDLERS
# ============================================================================

def register_group_chat_handlers(dp):
    """Регистрация обработчиков для групповых чатов"""
    dp.include_router(router)
