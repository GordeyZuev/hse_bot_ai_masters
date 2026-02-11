# ruff: noqa: ARG001
"""
Обработчики для групповых чатов и топиков.

Этот модуль содержит всю логику для работы с групповыми чатами:
- Настройка бота на предметы
- Управление настройками уведомлений
- Интерфейс для команды /start в чатах
- Callback обработчики для интерактивных кнопок
"""


import contextlib

from aiogram import F, Router
from aiogram.enums import ButtonStyle
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, and_f
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.bot.services.chat_notification_scheduler_service import (
    chat_notification_scheduler_service,
)
from src.bot.services.chat_service import chat_service
from src.bot.texts import (
    CHAT_CHANGE_SUBJECT_TEXT,
    CHAT_EDIT_REMINDER_TEXT,
    CHAT_EDIT_SETTINGS_TEXT,
    CHAT_NOT_CONFIGURED,
    ERROR_NO_PERMISSION,
    ERROR_NOT_ADMIN,
    GROUP_CHAT_HELP_TEXT,
    GROUP_START_CONFIGURED_TEXT,
    GROUP_START_UNCONFIGURED_TEXT,
    REMINDER1_SETUP_TEXT,
    REMINDER2_SETUP_TEXT,
    TIME_SETTINGS_SELECTED_SUBJECT_TEMPLATE,
)
from src.core.database import db_manager
from src.core.models import Subject
from src.core.models.models import Task
from src.utils import get_logger, safe_edit_message
from src.utils.notification_text import build_custom_offset_prompt, parse_offset_text


logger = get_logger()
router = Router()
# Утилита безопасной отправки сообщения: если топик закрыт, шлем в общий чат
async def _safe_send(message: Message, text: str, reply_markup=None, edit: bool = False):
    try:
        if edit:
            return await message.edit_text(text.strip(), reply_markup=reply_markup, parse_mode="HTML")
        return await message.answer(text.strip(), reply_markup=reply_markup, parse_mode="HTML")
    except TelegramBadRequest as e:
        err_str = str(e).lower()
        if "topic_closed" in err_str:
            # Падение из-за закрытого топика – отправляем в общий чат без thread_id
            return await message.bot.send_message(
                chat_id=message.chat.id,
                text=text.strip(),
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        if "message is not modified" in err_str or "message not found" in err_str:
            # Сообщение не изменилось или удалено - это нормально
            return None
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
    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id

        # Только админы
        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.answer(ERROR_NO_PERMISSION, show_alert=True)
            return

        await callback.answer()

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
        logger.error(f"(C) {chat_id} - привязка топика: {e}")
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
    waiting_custom_reminder = State()  # Для кастомного ввода времени


class ChatSwitchModeStates(StatesGroup):
    """Состояния для подтверждения переключения режима"""
    confirming_switch = State()


class ChatSettingsStates(StatesGroup):
    """Состояния для редактирования настроек бота"""
    waiting_reminder1_offset = State()
    waiting_reminder1_unit = State()
    waiting_reminder2_offset = State()
    waiting_reminder2_unit = State()
    waiting_custom_reminder = State()  # Для кастомного ввода времени


# ============================================================================
# СПРАВКА ДЛЯ ЧАТОВ
# ============================================================================

async def send_chat_help_message(message: Message, edit_mode: bool = False):
    """Отправка сообщения со справкой для групповых чатов"""
    try:

        text = GROUP_CHAT_HELP_TEXT

        builder = InlineKeyboardBuilder()
        # Кнопка настройки бота показывается только если бот уже настроен в этом чате
        try:
            chat_id = message.chat.id
            chat = await chat_service.get_chat(chat_id)
        except Exception:
            chat = None
        if chat:
            builder.button(text="⚙️ Настройка", callback_data="chat_settings_from_start")
        builder.button(text="🔙 Назад", callback_data="back_to_start")
        builder.adjust(1)

        if edit_mode:
            await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
        else:
            await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    except Exception:
        raise


async def show_chat_setup_interface(message: Message, edit_mode: bool = False):
    """Показать интерфейс настройки бота (когда еще не настроен)"""
    try:
        text = "📚 <b>Выберите режим работы бота:</b>\n\n"
        text += "🔹 <b>Single-mode:</b> Одна дисциплина на весь чат\n"
        text += "   Все топики будут отслеживать дедлайны одной и той же дисциплины. Настройка применяется ко всему чату сразу.\n\n"
        text += "🔹 <b>Multi-mode:</b> Каждый топик может иметь свою дисциплину\n"
        text += "   Можно настроить разные дисциплины для разных топиков. Настройка выполняется отдельно для каждого топика.\n"

        builder = InlineKeyboardBuilder()
        builder.button(text="1️⃣ Single-mode", callback_data="chat_setup_mode_single")
        builder.button(text="2️⃣ Multi-mode", callback_data="chat_setup_mode_multi")
        builder.button(text="🔙 Назад", callback_data="back_to_start")
        builder.adjust(1)

        if edit_mode:
            await message.edit_text(text.strip(), reply_markup=builder.as_markup(), parse_mode="HTML")
        else:
            await message.answer(text.strip(), reply_markup=builder.as_markup(), parse_mode="HTML")

    except Exception as e:
        chat_id = message.chat.id
        logger.error(f"(C) {chat_id} - показ интерфейса настройки бота: {e}")
        if not edit_mode:
            await message.answer("Произошла ошибка при настройке бота")


async def show_chat_multi_mode_overview(message: Message, chat, edit_mode: bool = False):
    """Показать обзор всех топиков в multi-mode из общего чата"""
    try:
        chat_id = message.chat.id

        # Получаем все настроенные топики
        topics = await chat_service.get_chat_groups_topics(chat_id)

        text = "⚙️ <b>Настройки бота</b>\n\n"
        text += "<b>🧩 Режим:</b> Multi-mode\n\n"

        if not topics:
            text += "<b>📋 Настроенные топики:</b>\n"
            text += "❌ Топики ещё не настроены.\n\n"
            text += "💡 <b>Как настроить:</b>\n"
            text += "1. Перейдите в нужный топик\n"
            text += "2. Вызовите /setup_discipline или нажмите «⚙️ Настроить бота»\n"
            text += "3. Выберите дисциплину и настройте уведомления\n"
        else:
            text += f"<b>📋 Настроенные топики ({len(topics)}):</b>\n\n"

            # Приводим единицы времени к человекочитаемым
            def unit_label(u: str) -> str:
                return "дн." if u == "days" else ("ч." if u == "hours" else u)

            for idx, topic in enumerate(topics, 1):
                topic_display = topic.topic_title or (f"ID {topic.topic_id}" if topic.topic_id else "Общий чат")
                status = "✅ Активен" if topic.is_active else "❌ Отключен"
                text += f"<b>{idx}. Топик «{topic_display}»</b>\n"
                text += f"   📚 {topic.subject.name}\n"
                text += f"   🔔 Первое: за {topic.reminder1_offset} {unit_label(topic.reminder1_unit)}\n"
                text += f"   🔔 Второе: за {topic.reminder2_offset} {unit_label(topic.reminder2_unit)}\n"
                text += f"   {status}\n\n"

            text += "💡 <i>Для настройки конкретного топика перейдите в него и зайдите в настройки (через /start)</i>\n"

        builder = InlineKeyboardBuilder()

        # Кнопки для управления
        builder.button(text="⚙️ Дополнительные настройки", callback_data="chat_advanced_settings")
        builder.button(text="🔙 Назад", callback_data="back_to_start")
        builder.adjust(1)

        if edit_mode:
            try:
                await message.edit_text(text.strip(), reply_markup=builder.as_markup(), parse_mode="HTML")
            except TelegramBadRequest as e:
                if "message is not modified" not in str(e):
                    raise
        else:
            await message.answer(text.strip(), reply_markup=builder.as_markup(), parse_mode="HTML")

    except Exception as e:
        logger.error(f"(C) {message.chat.id} - показ обзора multi-mode: {e}")
        if not edit_mode:
            await message.answer("Произошла ошибка при отображении настроек")


async def show_chat_settings_interface(message: Message, chat_topic, edit_mode: bool = False):
    """Показать интерфейс управления настройками бота (когда бот настроен)"""
    try:
        chat_id = message.chat.id

        # Получаем чат для режима
        chat = await chat_service.get_chat(chat_id)
        if not chat:
            await message.answer("❌ Чат не найден")
            return

        # Формируем информацию о настройках
        text = "⚙️ <b>Настройка</b>\n\n"

        # Приводим единицы времени к человекочитаемым
        def unit_label(u: str) -> str:
            return "дн." if u == "days" else ("ч." if u == "hours" else u)

        # Секция: Настройки (самое важное сверху)
        text += "<b>🧩 Настройки</b>:\n"
        text += f"• <b>Предмет:</b> «{chat_topic.subject.name}»\n"
        if chat_topic.topic_id:
            # В настройках сначала выводим сохранённое имя (если есть), затем пытаемся получить по API
            topic_title_saved = getattr(chat_topic, "topic_title", None)
            topic_title_api = None if topic_title_saved else await chat_service.get_topic_title(message.bot, chat_id, chat_topic.topic_id)
            topic_display = (topic_title_saved or topic_title_api) or f"ID {chat_topic.topic_id}"
            text += f"• <b>Топик:</b> «{topic_display}»\n"
        else:
            text += "• <b>Топик:</b> Общий чат\n"
        try:
            can_manage_topics = await chat_service.bot_can_manage_topics(message.bot, chat_id)
            status_topics = "✅ есть" if can_manage_topics else "❌ нет"
            text += f"• <b>Управление темами:</b> {status_topics}\n"
        except Exception:
            text += "• <b>Управление темами:</b> —\n"
        text += f"• <b>Статус:</b> {'✅ Включен' if chat_topic.is_active else '❌ Выключен'}\n"

        # Секция: Уведомления
        text += "\n<b>🔔 Уведомления</b>:\n"
        text += (
            f"• <b>Первое:</b> за {chat_topic.reminder1_offset} {unit_label(chat_topic.reminder1_unit)}\n"
        )
        text += (
            f"• <b>Второе:</b> за {chat_topic.reminder2_offset} {unit_label(chat_topic.reminder2_unit)}\n"
        )

        # Секция: Статистика
        text += "\n<b>📊 Статистика</b>:\n"

        # Добавляем статистику уведомлений
        try:
            async with db_manager.async_session() as session:
                from sqlalchemy import func, select

                from src.core.models.models import ChatScheduledNotification

                # Подсчитываем общее количество уведомлений для этого топика
                total_result = await session.execute(
                    select(func.count(ChatScheduledNotification.id)).where(
                        ChatScheduledNotification.chat_topic_id == chat_topic.id
                    )
                )
                total_notifications = total_result.scalar() or 0

                # Подсчитываем запланированные уведомления
                scheduled_result = await session.execute(
                    select(func.count(ChatScheduledNotification.id)).where(
                        ChatScheduledNotification.chat_topic_id == chat_topic.id,
                        ChatScheduledNotification.status == "scheduled"
                    )
                )
                scheduled_notifications = scheduled_result.scalar() or 0

                text += f"• Всего уведомлений: {total_notifications}\n"
                text += f"• Запланировано: {scheduled_notifications}\n"

        except Exception as e:
            logger.error(f"(C) {chat_id} - получение статистики уведомлений: {e}")


        builder = InlineKeyboardBuilder()
        builder.button(text="📚 Изменить дисциплину", callback_data="chat_change_subject")
        builder.button(text="⚙️ Настроить уведомления", callback_data="chat_edit_settings")
        # Добавляем переключатель уведомлений в общий раздел
        if chat_topic.is_active:
            builder.button(text="🔕 Отключить уведомления", callback_data="chat_toggle_active", style=ButtonStyle.DANGER)
        else:
            builder.button(text="🔔 Включить уведомления", callback_data="chat_toggle_active", style=ButtonStyle.SUCCESS)

        # Управление топиком (только в single-mode)
        if chat.mode == "single":
            builder.button(text="📍 Привязать к этому топику", callback_data="chat_set_topic_here")

        # Кнопка смены режима
        if chat.mode == "single":
            builder.button(text="🔄 Переключить чат в Multi-mode", callback_data="chat_switch_mode_multi")
        else:
            builder.button(text="🔄 Переключить чат в Single-mode", callback_data="chat_switch_mode_single")

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
        logger.error(f"(C) {chat_id} - показ интерфейса настроек бота: {e}")
        if not edit_mode:
            await message.answer("Произошла ошибка при получении настроек бота")


async def handle_start_in_group(message: Message, db_user, user_name: str):
    """Обработка команды /start в групповом чате"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    username = message.from_user.username

    logger.info(f"(C) {chat_id} - /start user=@{username or f'ID{user_id}'}")

    # Проверяем, настроен ли уже чат
    chat = await chat_service.get_chat(chat_id)

    if chat:
        if chat.mode == "multi":
            # Multi-mode: проверяем, из какого топика вызвана команда
            topic_id = await chat_service.get_topic_id_from_message(message)

            if topic_id is not None:
                # Вызов из конкретного топика - показываем информацию о топике
                chat_topic = await chat_service.get_chat_topic(chat_id, topic_id)
                if chat_topic:
                    text = GROUP_START_CONFIGURED_TEXT.format(
                        subject_name=chat_topic.subject.name,
                        status=("✅ Активен" if chat_topic.is_active else "❌ Отключен"),
                    )
                    builder = InlineKeyboardBuilder()
                    builder.button(text="ℹ️ Информация", callback_data="chat_info")
                    builder.button(text="⚙️ Настройка", callback_data="chat_settings_from_start")
                    builder.button(text="❓ Помощь", callback_data="quick_help")
                    builder.adjust(1)
                else:
                    # Топик не настроен
                    text = "📚 Этот топик еще не настроен на дисциплину.\n\n"
                    text += "Попросите администратора нажать «Настроить»."
                    builder = InlineKeyboardBuilder()
                    builder.button(text="⚙️ Настроить", callback_data="chat_setup_from_start")
                    builder.button(text="❓ Помощь", callback_data="quick_help")
                    builder.adjust(1)
            else:
                # Вызов из общего чата - показываем список всех топиков
                topics = await chat_service.get_chat_groups_topics(chat_id)
                if topics:
                    text = "📚 <b>Настроенные топики:</b>\n\n"
                    for topic in topics:
                        topic_display = topic.topic_title or (f"ID {topic.topic_id}" if topic.topic_id else "Общий чат")
                        status = "✅" if topic.is_active else "❌"
                        text += f"{status} <b>{topic_display}</b> — {topic.subject.name}\n"

                    builder = InlineKeyboardBuilder()
                    builder.button(text="⚙️ Настройка", callback_data="chat_settings_from_start")
                    builder.button(text="❓ Помощь", callback_data="quick_help")
                    builder.adjust(1)
                else:
                    text = "📚 Чат в multi-mode, но топики не настроены.\n\n"
                    text += "Настройте топики через /setup_discipline в каждом топике."
                    builder = InlineKeyboardBuilder()
                    builder.button(text="⚙️ Настроить", callback_data="chat_setup_from_start")
                    builder.button(text="❓ Помощь", callback_data="quick_help")
                    builder.adjust(1)
        else:
            # Single-mode: показываем информацию о единственном топике (игнорируем topic_id из сообщения)
            topics = await chat_service.get_chat_groups_topics(chat_id)
            if topics:
                chat_topic = topics[0]  # Берем первый (и единственный) топик
                text = GROUP_START_CONFIGURED_TEXT.format(
                    subject_name=chat_topic.subject.name,
                    status=("✅ Активен" if chat_topic.is_active else "❌ Отключен"),
                )

                builder = InlineKeyboardBuilder()
                builder.button(text="ℹ️ Информация", callback_data="chat_info")
                builder.button(text="⚙️ Настройка", callback_data="chat_settings_from_start")
                builder.button(text="❓ Помощь", callback_data="quick_help")
                builder.adjust(1)
            else:
                text = GROUP_START_UNCONFIGURED_TEXT
                builder = InlineKeyboardBuilder()
                builder.button(text="⚙️ Настроить", callback_data="chat_setup_from_start")
                builder.button(text="❓ Помощь", callback_data="quick_help")
                builder.adjust(1)
    else:
        # Чат не настроен — краткое приветствие и ссылка на помощь
        text = GROUP_START_UNCONFIGURED_TEXT

        builder = InlineKeyboardBuilder()
        builder.button(text="⚙️ Настроить", callback_data="chat_setup_from_start")
        builder.button(text="❓ Помощь", callback_data="quick_help")
        builder.adjust(1)

        # Для обычных пользователей добавим пояснение, что настраивать может только админ
        try:
            is_admin = await chat_service.is_chat_admin(message.bot, chat_id, user_id)
        except Exception:
            is_admin = False
        if not is_admin:
            text = text.strip() + "\n\n❗️ Настраивать бота может только администратор этого чата."

    # Используем _safe_send для автоматической обработки TOPIC_CLOSED
    await _safe_send(message, text.strip(), reply_markup=builder.as_markup())


@router.message(and_f(Command("help"), F.chat.type.in_(["group", "supergroup"])))
async def cmd_chat_help(message: Message, db_user):
    """Команда справки для групповых чатов"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    username = message.from_user.username

    logger.info(f"(C) {chat_id} - /help user=@{username or f'ID{user_id}'}")

    # Разрешаем только администраторам чата
    if not await chat_service.is_chat_admin(message.bot, chat_id, user_id):
        await message.answer(f"<b>{ERROR_NO_PERMISSION}</b>", parse_mode="HTML")
        return

    await send_chat_help_message(message)


@router.message(and_f(Command("setup_discipline"), F.chat.type.in_(["group", "supergroup"])))
async def cmd_setup_discipline(message: Message, db_user, state: FSMContext):
    """Команда настройки чата на предмет

    Поддерживает аргументы: /setup_discipline <название предмета>
    Если указано название, пытается найти предмет и настроить сразу.
    """

    chat_id = message.chat.id
    user_id = message.from_user.id
    username = message.from_user.username

    # Извлекаем аргументы команды (название предмета)
    command_args = message.text.split(maxsplit=1)[1:] if message.text else []
    subject_name_search = command_args[0].strip() if command_args else None

    logger.info(
        f"(C) {chat_id} - /setup_discipline user=@{username or f'ID{user_id}'}"
        + (f" arg='{subject_name_search}'" if subject_name_search else "")
    )

    try:
        if not await chat_service.is_chat_admin(message.bot, chat_id, user_id):
            await message.answer(
                f"<b>{ERROR_NO_PERMISSION}</b>",
                parse_mode="HTML",
            )
            return

        # Получаем topic_id если команда вызвана в топике
        topic_id = await chat_service.get_topic_id_from_message(message)

        # Проверяем, не настроен ли уже чат/топик
        existing_topic = await chat_service.get_chat_topic(chat_id, topic_id)
        if existing_topic:
            subject_name = existing_topic.subject.name
            topic_info = f" (топик {existing_topic.topic_id})" if existing_topic.topic_id else " (общий чат)"
            await message.answer(
                f"ℹ️ Этот топик уже настроен на предмет: <b>«{subject_name}»</b>{topic_info}\n\n"
                f"Используйте /chat_settings для изменения настроек",
                parse_mode="HTML"
            )
            return

        existing_chat = await chat_service.get_chat(chat_id)

        matched_subjects = []
        subjects = []
        async with db_manager.async_session() as session:
            from sqlalchemy import select

            if subject_name_search:
                stmt = (
                    select(Subject)
                    .where(Subject.is_active, Subject.name.ilike(f"%{subject_name_search}%"))
                    .order_by(Subject.name)
                )
                result = await session.execute(stmt)
                matched_subjects = list(result.scalars().all())

                if len(matched_subjects) == 1:
                    subject = matched_subjects[0]
                    logger.info(
                        f"(C) {chat_id} - Найдено точное совпадение: '{subject.name}' (ID: {subject.id}), "
                        f"настраиваем чат автоматически"
                    )

                    topic_title = None
                    if topic_id is not None:
                        topic_title = await _resolve_topic_title(message, chat_id, topic_id)
                        if not topic_title:
                            try:
                                topic_title = await chat_service.get_topic_title(message.bot, chat_id, topic_id)
                            except Exception:
                                topic_title = None

                    mode = existing_chat.mode if existing_chat else "single"

                    if mode == "multi" and topic_id is None:
                        await message.answer(
                            "❌ В multi-mode нельзя настраивать общий чат. Вызовите команду в топике.",
                            parse_mode="HTML"
                        )
                        return

                    success, message_text = await chat_service.setup_chat_group(
                        message.bot,
                        chat_id,
                        subject.id,
                        user_id,
                        topic_id,
                        mode=mode,
                        reminder1_offset=7,
                        reminder1_unit="days",
                        reminder2_offset=1,
                        reminder2_unit="days",
                        is_active=True,
                    )

                    if success:
                        if topic_id is not None and topic_title:
                            with contextlib.suppress(Exception):
                                await chat_service.update_chat_settings(
                                    chat_id=chat_id,
                                    user_id=user_id,
                                    bot=message.bot,
                                    topic_id=topic_id,
                                    topic_title=topic_title,
                                    topic_id_set=True,
                                )
                        topic_info = f" (топик {topic_id})" if topic_id else " (общий чат)"
                        await message.answer(
                            f"✅ Бот настроен на предмет <b>«{subject.name}»</b>{topic_info}!\n\n"
                            f"Используйте /chat_settings для изменения настроек.",
                            parse_mode="HTML"
                        )
                    else:
                        await message.answer(message_text, parse_mode="HTML")
                    return

                elif len(matched_subjects) > 1:
                    if existing_chat:
                        mode = existing_chat.mode
                    else:
                        await show_chat_setup_interface(message)
                        return
                    text = f"🔍 <b>Найдено несколько предметов по запросу «{subject_name_search}»:</b>\n\n"
                    subjects = matched_subjects
                else:
                    if existing_chat:
                        mode = existing_chat.mode
                    else:
                        await show_chat_setup_interface(message)
                        return
                    text = (
                        f"❌ Предмет по запросу «{subject_name_search}» не найден.\n\n"
                        "📚 <b>Доступные предметы:</b>\n\n"
                    )
                    stmt = select(Subject).where(Subject.is_active).order_by(Subject.name)
                    result = await session.execute(stmt)
                    subjects = list(result.scalars().all())
            else:
                if not existing_chat:
                    await show_chat_setup_interface(message)
                    return

                mode = existing_chat.mode

                stmt = select(Subject).where(Subject.is_active).order_by(Subject.name)
                result = await session.execute(stmt)
                subjects = list(result.scalars().all())
                if mode == "single":
                    text = "📚 <b>Выберите предмет для чата. Настройка будет действительна для всех топиков.</b>\n\n"
                else:
                    text = "📚 <b>Выберите предмет для топика. Настройка будет действительна только в рамках этого топика.</b>\n\n"

        if not subjects:
            await message.answer("❌ Нет доступных предметов для настройки")
            return

        if not subject_name_search or len(matched_subjects) != 1:
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
        logger.error(f"(C) {chat_id} - настройка дисциплины: {e}")
        await message.answer("Произошла ошибка при настройке бота")


@router.message(and_f(Command("chat_settings"), F.chat.type.in_(["group", "supergroup"])))
async def cmd_chat_settings(message: Message, db_user):
    """Команда показа настроек бота"""

    chat_id = message.chat.id
    user_id = message.from_user.id
    username = message.from_user.username

    logger.info(f"(C) {chat_id} - /chat_settings user=@{username or f'ID{user_id}'}")

    try:
        # Проверяем права доступа
        if not await chat_service.is_chat_admin(message.bot, chat_id, user_id):
            await message.answer(
                f"<b>{ERROR_NO_PERMISSION}</b>",
                parse_mode="HTML",
            )
            return

        # Получаем topic_id если команда вызвана в топике
        topic_id = await chat_service.get_topic_id_from_message(message)

        # Получаем чат
        chat = await chat_service.get_chat(chat_id)
        if not chat:
            # Чат не настроен - показываем интерфейс настройки
            await show_chat_setup_interface(message)
            return

        # В multi-mode из общего чата показываем обзор топиков
        if chat.mode == "multi" and topic_id is None:
            await show_chat_multi_mode_overview(message, chat)
            return

        # Получаем топик
        if chat.mode == "single":
            # В single-mode игнорируем topic_id и получаем единственный топик
            topics = await chat_service.get_chat_groups_topics(chat_id)
            chat_topic = topics[0] if topics else None
        else:
            # В multi-mode используем topic_id
            chat_topic = await chat_service.get_chat_topic(chat_id, topic_id)

        if not chat_topic:
            # Топик не настроен - показываем интерфейс настройки
            await show_chat_setup_interface(message)
        else:
            # Топик настроен - показываем интерфейс управления настройками
            await show_chat_settings_interface(message, chat_topic)

    except Exception as e:
        logger.error(f"(C) {chat_id} - настройки чата: {e}")
        await message.answer("Произошла ошибка при получении настроек бота")


@router.message(and_f(Command("disable_chat"), F.chat.type.in_(["group", "supergroup"])))
async def cmd_disable_chat(message: Message, db_user):
    """Команда отключения уведомлений в чате"""

    chat_id = message.chat.id
    user_id = message.from_user.id
    username = message.from_user.username

    logger.info(f"(C) {chat_id} - /disable_chat user=@{username or f'ID{user_id}'}")

    try:
        success, message_text = await chat_service.toggle_chat_active(chat_id, user_id, message.bot)
        await message.answer(message_text)

    except Exception as e:
        logger.error(f"(C) {chat_id} - отключение чата: {e}")
        await message.answer("Произошла ошибка при отключении бота")


# ============================================================================
# CALLBACK ОБРАБОТЧИКИ ДЛЯ НАСТРОЙКИ ЧАТА
# ============================================================================

@router.callback_query(F.data.startswith("chat_setup_subject_"))
async def callback_setup_chat_subject(callback: CallbackQuery, db_user, state: FSMContext):
    """Обработчик выбора предмета для настройки бота"""
    try:
        subject_id = int(callback.data.split("_")[-1])
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        username = callback.from_user.username

        logger.info(f"(C) {chat_id} - setup_chat_subject_{subject_id} user=@{username or f'ID{user_id}'}")

        # Только админы
        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.answer(ERROR_NO_PERMISSION, show_alert=True)
            return

        await callback.answer()

        # Получаем данные из состояния (режим и topic_id)
        data = await state.get_data()
        mode = data.get("mode")
        topic_id = data.get("topic_id")

        # Если topic_id не в состоянии, получаем из сообщения
        if topic_id is None:
            topic_id = await chat_service.get_topic_id_from_message(callback.message)

        # В multi-mode проверяем, что topic_id установлен
        if mode == "multi" and topic_id is None:
            await safe_edit_message(
                callback.message,
                "❌ В multi-mode нельзя настраивать общий чат. Вызовите команду в топике.",
                parse_mode="HTML"
            )
            return

        if mode is None:
            chat = await chat_service.get_chat(chat_id)
            mode = chat.mode if chat else None

        if mode is None:
            await safe_edit_message(callback.message, "❌ Сначала выберите режим работы бота", parse_mode="HTML")
            return

        # Попробуем сразу определить и сохранить человекочитаемое название топика
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

        # Создаем чат с дефолтными настройками и сразу переводим в раздел настроек
        success, message_text = await chat_service.setup_chat_group(
            callback.bot,
            chat_id,
            subject_id,
            user_id,
            topic_id,
            mode=mode,
            reminder1_offset=7,
            reminder1_unit="days",
            reminder2_offset=1,
            reminder2_unit="days",
            is_active=True,
        )

        if success:
            # Если определили название топика — сразу сохраним его в БД
            if topic_id is not None and topic_title:
                with contextlib.suppress(Exception):
                    await chat_service.update_chat_settings(
                        chat_id=chat_id,
                        user_id=user_id,
                        bot=callback.bot,
                        topic_id=topic_id,
                        topic_title=topic_title,
                        topic_id_set=True,
                    )
            # Получаем топик с учетом режима
            chat = await chat_service.get_chat(chat_id)
            if chat and chat.mode == "single":
                topics = await chat_service.get_chat_groups_topics(chat_id)
                chat_topic = topics[0] if topics else None
            else:
                chat_topic = await chat_service.get_chat_topic(chat_id, topic_id)

            if chat_topic:
                await show_chat_settings_interface(callback.message, chat_topic, edit_mode=True)
            else:
                await safe_edit_message(callback.message, "✅ Чат настроен!", parse_mode="HTML")
        else:
            await safe_edit_message(callback.message, message_text, parse_mode="HTML")

        await state.clear()

    except Exception as e:
        logger.error(f"(C) {callback.message.chat.id} - выбор предмета: {e}")
        await safe_edit_message(callback.message, "Произошла ошибка при настройке бота")


@router.callback_query(F.data == "chat_setup_cancel")
async def callback_setup_chat_cancel(callback: CallbackQuery, db_user, state: FSMContext):
    """Отмена настройки бота: сразу возвращаем в главное меню"""
    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        username = callback.from_user.username

        logger.info(f"(C) {chat_id} - setup_cancel user=@{username or f'ID{user_id}'}")

        # Только админы
        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.answer(ERROR_NO_PERMISSION, show_alert=True)
            return

        await callback.answer()
        await state.clear()
        # Возврат к главному экрану (единая инструкция)
        await callback_back_to_start(callback, db_user)

    except Exception as e:
        logger.error(f"(C) {chat_id} - отмена настройки: {e}")
        await safe_edit_message(callback.message, "Произошла ошибка при отмене настройки")


@router.callback_query(F.data == "chat_setup_reminder1")
async def callback_setup_reminder1(callback: CallbackQuery, db_user, state: FSMContext):
    """Настройка первого напоминания"""
    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id

        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.answer(ERROR_NO_PERMISSION, show_alert=True)
            return

        await callback.answer()

        text = REMINDER1_SETUP_TEXT

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

        builder.button(
            text="✏️ Свой вариант",
            callback_data="chat_custom_reminder_1"
        )
        builder.button(text="🔙 Назад", callback_data="chat_setup_from_start")
        builder.adjust(2)

        await safe_edit_message(callback.message, text.strip(), reply_markup=builder.as_markup(), parse_mode="HTML")
        await state.set_state(ChatSetupStates.waiting_reminder1_selection)

    except Exception as e:
        chat_id = callback.message.chat.id
        logger.error(f"(C) {chat_id} - настройка первого напоминания: {e}")
        await safe_edit_message(callback.message, "Произошла ошибка при настройке напоминания")


@router.callback_query(F.data == "chat_setup_reminder2")
async def callback_setup_reminder2(callback: CallbackQuery, db_user, state: FSMContext):
    """Настройка второго напоминания"""
    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id

        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.answer(ERROR_NO_PERMISSION, show_alert=True)
            return

        await callback.answer()

        text = REMINDER2_SETUP_TEXT

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

        builder.button(
            text="✏️ Свой вариант",
            callback_data="chat_custom_reminder_2"
        )
        builder.button(text="🔙 Назад", callback_data="chat_setup_from_start")
        builder.adjust(2)

        await safe_edit_message(callback.message, text.strip(), reply_markup=builder.as_markup(), parse_mode="HTML")
        await state.set_state(ChatSetupStates.waiting_reminder2_selection)

    except Exception as e:
        chat_id = callback.message.chat.id
        logger.error(f"(C) {chat_id} - настройка второго напоминания: {e}")
        await safe_edit_message(callback.message, "Произошла ошибка при настройке напоминания")


@router.callback_query(F.data == "chat_setup_finish")
async def callback_setup_finish(callback: CallbackQuery, db_user, state: FSMContext):
    """Завершение настройки бота"""
    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        username = callback.from_user.username

        logger.info(f"(C) {chat_id} - setup_finish user=@{username or f'ID{user_id}'}")

        # Только админы
        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.answer(ERROR_NO_PERMISSION, show_alert=True)
            return

        await callback.answer()

        # Получаем данные из состояния
        data = await state.get_data()
        subject_id = data.get("subject_id")
        topic_id = data.get("topic_id")
        reminder1_offset = data.get("reminder1_offset", 7)
        reminder1_unit = data.get("reminder1_unit", "days")
        reminder2_offset = data.get("reminder2_offset", 1)
        reminder2_unit = data.get("reminder2_unit", "days")

        if not subject_id:
            await safe_edit_message(callback.message, "❌ Ошибка: предмет не выбран")
            await state.clear()
            return

        # Настраиваем чат
        success, message_text = await chat_service.setup_chat_group(
            callback.bot, chat_id, subject_id, user_id, topic_id,
            reminder1_offset=reminder1_offset,
            reminder1_unit=reminder1_unit,
            reminder2_offset=reminder2_offset,
            reminder2_unit=reminder2_unit,
            is_active=True,
        )

        if success:
            # Если привязали к топику — сохраним человекочитаемое имя топика
            if topic_id is not None:
                try:
                    topic_title = await _resolve_topic_title(callback.message, chat_id, topic_id)
                    if not topic_title:
                        try:
                            topic_title = await chat_service.get_topic_title(callback.bot, chat_id, topic_id)
                        except Exception:
                            topic_title = None
                    if topic_title:
                        await chat_service.update_chat_settings(
                            chat_id=chat_id,
                            user_id=user_id,
                            bot=callback.bot,
                            topic_id=topic_id,
                            topic_title=topic_title,
                            topic_id_set=True,
                        )
                except Exception:
                    pass

            # Получаем топик с учетом режима для планирования уведомлений
            chat = await chat_service.get_chat(chat_id)
            chat_topic = None
            if chat:
                if chat.mode == "single":
                    topics = await chat_service.get_chat_groups_topics(chat_id)
                    chat_topic = topics[0] if topics else None
                else:
                    chat_topic = await chat_service.get_chat_topic(chat_id, topic_id)

            # Планируем уведомления для нового чата
            scheduled_count = await chat_notification_scheduler_service.schedule_notifications_for_chat_subscription(
                chat_id, subject_id, chat_topic=chat_topic
            )

            message_text += f"\n\n📅 Запланировано {scheduled_count} уведомлений"

            # Предлагаем удалить сообщение
            builder = InlineKeyboardBuilder()
            builder.button(text="🗑️ Удалить сообщение", callback_data="chat_delete_message", style=ButtonStyle.DANGER)
            builder.button(text="🔙 Назад", callback_data="back_to_start")
            builder.adjust(1)

            await callback.message.edit_text(message_text, reply_markup=builder.as_markup(), parse_mode="HTML")
        else:
            await safe_edit_message(callback.message, message_text, parse_mode="HTML")

        await state.clear()

    except Exception as e:
        logger.error(f"(C) {chat_id} - завершение настройки: {e}")
        await safe_edit_message(callback.message, "Произошла ошибка при завершении настройки")


@router.callback_query(F.data.startswith("chat_setup_reminder1_"))
async def callback_set_reminder1_value(callback: CallbackQuery, db_user, state: FSMContext):
    """Установка значения первого напоминания"""
    try:
        # Парсим данные
        parts = callback.data.split("_")
        offset = int(parts[3])
        unit = parts[4]

        chat_id = callback.message.chat.id
        user_id = callback.from_user.id

        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.answer(ERROR_NO_PERMISSION, show_alert=True)
            return

        await callback.answer()

        # Сохраняем в состоянии
        await state.update_data(reminder1_offset=offset, reminder1_unit=unit)

        # Возвращаемся к настройке времени
        data = await state.get_data()
        subject_id = data.get("subject_id")
        subject = await db_manager.get_subject_by_id(subject_id)

        text = (
            TIME_SETTINGS_SELECTED_SUBJECT_TEMPLATE.format(subject_name=subject.name)
            + f"• Первое напоминание: за {offset} {unit}\n"
        )

        builder = InlineKeyboardBuilder()
        builder.button(text="1️⃣ Первое напоминание", callback_data="chat_setup_reminder1")
        builder.button(text="2️⃣ Второе напоминание", callback_data="chat_setup_reminder2")
        builder.button(text="✅ Завершить настройку", callback_data="chat_setup_finish", style=ButtonStyle.SUCCESS)
        builder.button(text="🔙 Назад", callback_data="chat_setup_from_start")
        builder.adjust(1)

        await safe_edit_message(callback.message, text.strip(), reply_markup=builder.as_markup(), parse_mode="HTML")
        await state.set_state(ChatSetupStates.waiting_time_settings)

    except Exception as e:
        chat_id = callback.message.chat.id
        logger.error(f"(C) {chat_id} - установка первого напоминания: {e}")
        await safe_edit_message(callback.message, "Произошла ошибка при настройке напоминания")


@router.callback_query(F.data.startswith("chat_setup_reminder2_"))
async def callback_set_reminder2_value(callback: CallbackQuery, db_user, state: FSMContext):
    """Установка значения второго напоминания"""
    try:
        # Парсим данные
        parts = callback.data.split("_")
        offset = int(parts[3])
        unit = parts[4]

        chat_id = callback.message.chat.id
        user_id = callback.from_user.id

        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.answer(ERROR_NO_PERMISSION, show_alert=True)
            return

        await callback.answer()

        # Сохраняем в состоянии
        await state.update_data(reminder2_offset=offset, reminder2_unit=unit)

        # Возвращаемся к настройке времени
        data = await state.get_data()
        subject_id = data.get("subject_id")
        subject = await db_manager.get_subject_by_id(subject_id)

        text = (
            TIME_SETTINGS_SELECTED_SUBJECT_TEMPLATE.format(subject_name=subject.name)
            + f"• Второе напоминание: за {offset} {unit}\n"
        )

        builder = InlineKeyboardBuilder()
        builder.button(text="1️⃣ Первое напоминание", callback_data="chat_setup_reminder1")
        builder.button(text="2️⃣ Второе напоминание", callback_data="chat_setup_reminder2")
        builder.button(text="✅ Завершить настройку", callback_data="chat_setup_finish", style=ButtonStyle.SUCCESS)
        builder.button(text="🔙 Назад", callback_data="chat_setup_from_start")
        builder.adjust(1)

        await safe_edit_message(callback.message, text.strip(), reply_markup=builder.as_markup(), parse_mode="HTML")
        await state.set_state(ChatSetupStates.waiting_time_settings)

    except Exception as e:
        chat_id = callback.message.chat.id
        logger.error(f"(C) {chat_id} - установка второго напоминания: {e}")
        await safe_edit_message(callback.message, "Произошла ошибка при настройке напоминания")


@router.callback_query(F.data == "chat_delete_message")
async def callback_delete_message(callback: CallbackQuery, db_user):
    """Удаление сообщения после настройки"""
    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id

        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.answer(ERROR_NOT_ADMIN, show_alert=True)
            return

        await callback.answer()
        await callback.message.delete()
    except Exception as e:
        chat_id = callback.message.chat.id
        logger.error(f"(C) {chat_id} - удаление сообщения: {e}")
        await safe_edit_message(callback.message, "❌ Не удалось удалить сообщение")


async def _show_subject_selection(
    callback: CallbackQuery,
    subjects: list[Subject],
    state: FSMContext,
    mode: str,
    *,
    edit_mode: bool = True,
) -> None:
    """Показать список предметов для выбора"""
    if mode == "single":
        text = "📚 <b>Выберите предмет для чата. Настройка будет действительна для всех топиков.</b>\n\n"
    else:
        text = "📚 <b>Выберите предмет для топика. Настройка будет действительна только в рамках этого топика.</b>\n\n"

    builder = InlineKeyboardBuilder()
    for subject in subjects:
        builder.button(
            text=f"📖 {subject.name}",
            callback_data=f"chat_setup_subject_{subject.id}"
        )

    builder.button(text="❌ Отмена", callback_data="chat_setup_cancel")
    builder.adjust(1)

    await state.set_state(ChatSetupStates.waiting_subject_selection)
    if edit_mode:
        await safe_edit_message(callback.message, text, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        await callback.message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data == "chat_setup_from_start")
async def callback_setup_from_start(callback: CallbackQuery, db_user, state: FSMContext):
    """Обработчик кнопки настройки бота из /start"""
    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        username = callback.from_user.username

        logger.info(f"(C) {chat_id} - setup_from_start user=@{username or f'ID{user_id}'}")

        # Проверяем права админа
        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.answer(ERROR_NO_PERMISSION, show_alert=True)
            return

        await callback.answer()

        chat = await chat_service.get_chat(chat_id)
        topic_id = await chat_service.get_topic_id_from_message(callback.message)

        if chat:
            mode = chat.mode
            # В multi-mode из общего чата показываем обзор топиков
            if mode == "multi" and topic_id is None:
                await show_chat_multi_mode_overview(callback.message, chat, edit_mode=True)
                return

            # В multi-mode из топика или single-mode - настраиваем топик
            await state.update_data(mode=mode, topic_id=topic_id)

            # Получаем список доступных предметов
            async with db_manager.async_session() as session:
                from sqlalchemy import select
                stmt = select(Subject).where(Subject.is_active).order_by(Subject.name)
                result = await session.execute(stmt)
                subjects = list(result.scalars().all())

            if not subjects:
                await safe_edit_message(callback.message, "❌ Нет доступных предметов для настройки")
                return

            await _show_subject_selection(callback, subjects, state, mode, edit_mode=True)
        else:
            # Чат не существует - показываем выбор режима
            await state.clear()
            await show_chat_setup_interface(callback.message, edit_mode=True)

    except Exception as e:
        logger.error(f"(C) {callback.message.chat.id} - настройка из стартового меню: {e}")
        await safe_edit_message(callback.message, "Произошла ошибка при настройке бота")


@router.callback_query(F.data.startswith("chat_setup_mode_"))
async def callback_setup_mode(callback: CallbackQuery, db_user, state: FSMContext):
    """Обработчик выбора режима чата"""
    try:
        mode = callback.data.split("_")[-1]  # 'single' или 'multi'
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        username = callback.from_user.username

        logger.info(f"(C) {chat_id} - setup_mode_{mode} user=@{username or f'ID{user_id}'}")

        # Проверяем права админа
        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.answer(ERROR_NO_PERMISSION, show_alert=True)
            return

        await callback.answer()

        # Получаем topic_id если команда вызвана в топике
        topic_id = await chat_service.get_topic_id_from_message(callback.message)

        # Сохраняем режим и topic_id в состояние
        await state.update_data(mode=mode, topic_id=topic_id)

        # В multi-mode при первой настройке из общего чата просто сохраняем режим
        # Пользователь потом перейдет в топик и настроит его
        if mode == "multi" and topic_id is None:
            # Создаем чат с выбранным режимом (без топика)
            # Это позволит пользователю потом настроить топики
            try:
                # Получаем информацию о чате для создания записи
                chat_info = await callback.bot.get_chat(chat_id)
                chat_type = chat_info.type
                chat_title = getattr(chat_info, "title", None)

                # Создаем чат с выбранным режимом
                async with db_manager.async_session() as session:
                    from src.core.models import ChatGroup
                    chat_group = ChatGroup(
                        chat_id=chat_id,
                        mode=mode,
                        chat_title=chat_title,
                        chat_type=chat_type,
                    )
                    session.add(chat_group)
                    await session.commit()

                text = "✅ <b>Режим Multi-mode установлен!</b>\n\n"
                text += "💡 <b>Что дальше?</b>\n"
                text += "1. Перейдите в нужный топик\n"
                text += "2. Вызовите /setup_discipline или нажмите «⚙️ Настроить бота»\n"
                text += "3. Выберите дисциплину и настройте уведомления\n\n"
                text += "Каждый топик настраивается отдельно."

                builder = InlineKeyboardBuilder()
                builder.button(text="🔙 Назад", callback_data="back_to_start")
                builder.adjust(1)

                await safe_edit_message(callback.message, text, reply_markup=builder.as_markup(), parse_mode="HTML")
                await state.clear()
                return
            except Exception as e:
                logger.error(f"(C) {chat_id} - создание чата с режимом: {e}")
                await safe_edit_message(
                    callback.message,
                    "❌ Произошла ошибка при установке режима. Попробуйте ещё раз.",
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
            await safe_edit_message(callback.message, "❌ Нет доступных предметов для настройки")
            return

        await _show_subject_selection(callback, subjects, state, mode, edit_mode=True)

    except Exception as e:
        logger.error(f"(C) {callback.message.chat.id} - выбор режима: {e}")
        await safe_edit_message(callback.message, "Произошла ошибка при выборе режима")


@router.callback_query(F.data == "chat_settings_from_start")
async def callback_settings_from_start(callback: CallbackQuery, db_user, state: FSMContext):
    """Обработчик кнопки настроек бота из /start"""
    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        username = callback.from_user.username

        logger.info(f"(C) {chat_id} - settings_from_start user=@{username or f'ID{user_id}'}")

        # Проверяем права доступа
        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.answer(ERROR_NO_PERMISSION, show_alert=True)
            return

        await callback.answer()

        # Получаем чат и topic_id
        chat = await chat_service.get_chat(chat_id)
        topic_id = await chat_service.get_topic_id_from_message(callback.message)

        if not chat:
            # Чат ещё не настроен - показываем выбор режима
            await state.clear()
            await show_chat_setup_interface(callback.message, edit_mode=True)
            return

        # В multi-mode из общего чата показываем обзор топиков
        if chat.mode == "multi" and topic_id is None:
            await show_chat_multi_mode_overview(callback.message, chat, edit_mode=True)
            return

        # Получаем топик
        if chat.mode == "single":
            # В single-mode игнорируем topic_id и получаем единственный топик
            topics = await chat_service.get_chat_groups_topics(chat_id)
            chat_topic = topics[0] if topics else None
        else:
            # В multi-mode используем topic_id
            chat_topic = await chat_service.get_chat_topic(chat_id, topic_id)

        if not chat_topic:
            # Топик не настроен - показываем выбор дисциплины
            # В single-mode topic_id не важен, в multi-mode используем topic_id из сообщения
            await state.update_data(mode=chat.mode, topic_id=topic_id if chat.mode == "multi" else None)

            async with db_manager.async_session() as session:
                from sqlalchemy import select
                stmt = select(Subject).where(Subject.is_active).order_by(Subject.name)
                result = await session.execute(stmt)
                subjects = list(result.scalars().all())

            if not subjects:
                await safe_edit_message(callback.message, "❌ Нет доступных предметов для настройки")
                return

            await _show_subject_selection(callback, subjects, state, chat.mode, edit_mode=True)
        else:
            # Топик настроен - показываем интерфейс управления настройками
            await show_chat_settings_interface(callback.message, chat_topic, edit_mode=True)

    except Exception as e:
        logger.error(f"(C) {chat_id} - настройки из стартового меню: {e}")
        await safe_edit_message(callback.message, "Произошла ошибка при получении настроек бота")


@router.callback_query(F.data == "back_to_start")
async def callback_back_to_start(callback: CallbackQuery, db_user):
    """Возврат к /start"""
    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        username = callback.from_user.username

        logger.info(f"(C) {chat_id} - back_to_start user=@{username or f'ID{user_id}'}")

        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.answer(ERROR_NOT_ADMIN, show_alert=True)
            return

        await callback.answer()

        # Получаем чат и топик
        chat = await chat_service.get_chat(chat_id)
        topic_id = await chat_service.get_topic_id_from_message(callback.message)

        if not chat:
            # Чат не настроен — единая инструкция
            text = GROUP_START_UNCONFIGURED_TEXT

            builder = InlineKeyboardBuilder()
            builder.button(text="⚙️ Настроить", callback_data="chat_setup_from_start")
            builder.button(text="❓ Помощь", callback_data="quick_help")
            builder.adjust(1)
        elif chat.mode == "multi" and topic_id is None:
            # Multi-mode из общего чата - показываем список топиков
            topics = await chat_service.get_chat_groups_topics(chat_id)
            if topics:
                text = "📚 <b>Настроенные топики:</b>\n\n"
                for topic in topics:
                    topic_display = topic.topic_title or (f"ID {topic.topic_id}" if topic.topic_id else "Общий чат")
                    status = "✅" if topic.is_active else "❌"
                    text += f"{status} <b>{topic_display}</b> — {topic.subject.name}\n"

                builder = InlineKeyboardBuilder()
                builder.button(text="⚙️ Настройка", callback_data="chat_settings_from_start")
                builder.button(text="❓ Помощь", callback_data="quick_help")
                builder.adjust(1)
            else:
                text = "📚 Чат в multi-mode, но топики не настроены.\n\n"
                text += "Настройте топики через /setup_discipline в каждом топике."
                builder = InlineKeyboardBuilder()
                builder.button(text="⚙️ Настроить", callback_data="chat_setup_from_start")
                builder.button(text="❓ Помощь", callback_data="quick_help")
                builder.adjust(1)
        elif chat.mode == "single":
            # Single-mode: показываем информацию о единственном топике (игнорируем topic_id)
            topics = await chat_service.get_chat_groups_topics(chat_id)
            if topics:
                chat_topic = topics[0]  # Берем первый (и единственный) топик
                text = GROUP_START_CONFIGURED_TEXT.format(
                    subject_name=chat_topic.subject.name,
                    status=("✅ Активен" if chat_topic.is_active else "❌ Отключен"),
                )

                builder = InlineKeyboardBuilder()
                builder.button(text="ℹ️ Информация", callback_data="chat_info")
                builder.button(text="⚙️ Настройка", callback_data="chat_settings_from_start")
                builder.button(text="❓ Помощь", callback_data="quick_help")
                builder.adjust(1)
            else:
                # Топик не настроен
                text = GROUP_START_UNCONFIGURED_TEXT

                builder = InlineKeyboardBuilder()
                builder.button(text="⚙️ Настроить", callback_data="chat_setup_from_start")
                builder.button(text="❓ Помощь", callback_data="quick_help")
                builder.adjust(1)
        else:
            # Multi-mode из топика
            chat_topic = await chat_service.get_chat_topic(chat_id, topic_id)

            if chat_topic:
                text = GROUP_START_CONFIGURED_TEXT.format(
                    subject_name=chat_topic.subject.name,
                    status=("✅ Активен" if chat_topic.is_active else "❌ Отключен"),
                )

                builder = InlineKeyboardBuilder()
                builder.button(text="ℹ️ Информация", callback_data="chat_info")
                builder.button(text="⚙️ Настройка топика", callback_data="chat_settings_from_start")
                builder.button(text="❓ Помощь", callback_data="quick_help")
                builder.adjust(1)
            else:
                # Топик не настроен
                text = GROUP_START_UNCONFIGURED_TEXT

                builder = InlineKeyboardBuilder()
                builder.button(text="⚙️ Настроить топик", callback_data="chat_setup_from_start")
                builder.button(text="❓ Помощь", callback_data="quick_help")
                builder.adjust(1)

        await safe_edit_message(callback.message, text.strip(), reply_markup=builder.as_markup(), parse_mode="HTML")

    except Exception as e:
        logger.error(f"(C) {chat_id} - возврат к стартовому меню: {e}")
        await safe_edit_message(callback.message, "Произошла ошибка при возврате к главному меню")


@router.callback_query(F.data == "chat_change_subject")
async def callback_change_subject(callback: CallbackQuery, db_user, state: FSMContext):
    """Смена дисциплины чата/топика"""
    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        username = callback.from_user.username

        logger.info(f"(C) {chat_id} - change_subject user=@{username or f'ID{user_id}'}")

        # Проверяем права доступа
        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.answer(ERROR_NOT_ADMIN, show_alert=True)
            return

        await callback.answer()

        # Получаем чат для определения режима
        chat = await chat_service.get_chat(chat_id)
        if not chat:
            await safe_edit_message(callback.message, "❌ Чат не найден")
            return

        # Получаем topic_id
        topic_id = await chat_service.get_topic_id_from_message(callback.message)

        # Получаем топик с учетом режима
        if chat.mode == "single":
            topics = await chat_service.get_chat_groups_topics(chat_id)
            chat_topic = topics[0] if topics else None
        else:
            chat_topic = await chat_service.get_chat_topic(chat_id, topic_id)

        if not chat_topic:
            await safe_edit_message(callback.message, "❌ Топик не найден")
            return

        async with db_manager.async_session() as session:
            from sqlalchemy import and_, select

            # Исключаем текущий предмет
            current_subject_id = chat_topic.subject_id
            stmt = (
                select(Subject)
                .where(
                    and_(
                        Subject.is_active,
                        Subject.id != current_subject_id
                    )
                )
                .order_by(Subject.name)
            )
            result = await session.execute(stmt)
            subjects = list(result.scalars().all())

        text = CHAT_CHANGE_SUBJECT_TEXT

        builder = InlineKeyboardBuilder()

        for subject in subjects:
            builder.button(
                text=f"📖 {subject.name}",
                callback_data=f"chat_change_subject_{subject.id}"
            )

        builder.button(text="🔙 Назад", callback_data="chat_settings_from_start")
        builder.adjust(1)

        # В single-mode topic_id не важен, в multi-mode используем topic_id из сообщения
        await state.update_data(topic_id=topic_id if chat.mode == "multi" else None)
        await safe_edit_message(callback.message, text.strip(), reply_markup=builder.as_markup(), parse_mode="HTML")
        await state.set_state(ChatSetupStates.waiting_subject_selection)

    except Exception as e:
        logger.error(f"(C) {chat_id} - смена предмета: {e}")
        await safe_edit_message(callback.message, "Произошла ошибка при смене дисциплины")


@router.callback_query(F.data.startswith("chat_change_subject_"))
async def callback_change_subject_selected(callback: CallbackQuery, db_user, state: FSMContext):
    """Обработчик выбора новой дисциплины"""
    try:
        subject_id = int(callback.data.split("_")[-1])
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        # Админ-проверка на всякий случай
        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.answer(ERROR_NOT_ADMIN, show_alert=True)
            return

        await callback.answer()
        username = callback.from_user.username

        logger.info(f"(C) {chat_id} - change_subject_{subject_id} user=@{username or f'ID{user_id}'}")

        # Получаем новую дисциплину
        await db_manager.get_subject_by_id(subject_id)

        # Получаем topic_id из состояния
        data = await state.get_data()
        topic_id = data.get("topic_id")
        if topic_id is None:
            topic_id = await chat_service.get_topic_id_from_message(callback.message)

        # Обновляем дисциплину топика
        success, message_text = await chat_service.change_chat_subject(
            callback.bot, chat_id, subject_id, user_id, topic_id
        )

        if success:
            # Перепланируем уведомления для новой дисциплины
            rescheduled_count = await chat_notification_scheduler_service.reschedule_notifications_for_chat_subject_change(
                chat_id, topic_id, subject_id
            )

            # Получаем обновленный топик с новой дисциплиной
            chat = await chat_service.get_chat(chat_id)
            if chat and chat.mode == "single":
                topics = await chat_service.get_chat_groups_topics(chat_id)
                chat_topic = topics[0] if topics else None
            else:
                chat_topic = await chat_service.get_chat_topic(chat_id, topic_id)

            if chat_topic:
                # Показываем обновленный интерфейс настроек
                await show_chat_settings_interface(callback.message, chat_topic, edit_mode=True)

                # Показываем уведомление о перепланировании
                if rescheduled_count > 0:
                    await callback.answer(f"✅ Дисциплина изменена. Перепланировано {rescheduled_count} уведомлений", show_alert=False)
                else:
                    await callback.answer("✅ Дисциплина изменена", show_alert=False)
        else:
            await safe_edit_message(callback.message, message_text, parse_mode="HTML")
            await callback.answer(message_text, show_alert=True)

        await state.clear()

    except Exception as e:
        logger.error(f"(C) {chat_id} - выбор нового предмета: {e}")
        await safe_edit_message(callback.message, "Произошла ошибка при смене дисциплины")

@router.callback_query(F.data.startswith("chat_edit_settings"))
async def callback_edit_chat_settings(callback: CallbackQuery, db_user):
    """Редактирование настроек бота"""
    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id

        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.answer(ERROR_NOT_ADMIN, show_alert=True)
            return

        await callback.answer()

        # Получаем чат для определения режима
        chat = await chat_service.get_chat(chat_id)
        if not chat:
            await safe_edit_message(callback.message, "❌ Чат не найден")
            return

        # Получаем topic_id из сообщения (в multi-mode используется, в single-mode игнорируется)
        topic_id = await chat_service.get_topic_id_from_message(callback.message)

        # Получаем топик с учетом режима
        if chat.mode == "single":
            topics = await chat_service.get_chat_groups_topics(chat_id)
            chat_topic = topics[0] if topics else None
        else:
            chat_topic = await chat_service.get_chat_topic(chat_id, topic_id)

        if not chat_topic:
            await safe_edit_message(callback.message, "❌ Топик не настроен")
            return

        text = CHAT_EDIT_SETTINGS_TEXT.format(
            subject_name=chat_topic.subject.name,
            reminder1_offset=chat_topic.reminder1_offset,
            reminder1_unit=chat_topic.reminder1_unit,
            reminder2_offset=chat_topic.reminder2_offset,
            reminder2_unit=chat_topic.reminder2_unit,
        )

        builder = InlineKeyboardBuilder()
        builder.button(text="1️⃣ Первое напоминание", callback_data="chat_edit_reminder1")
        builder.button(text="2️⃣ Второе напоминание", callback_data="chat_edit_reminder2")
        # Переключатель уведомлений переносим из этого раздела в общий, поэтому удалён
        builder.button(text="🔙 Назад", callback_data="chat_settings_from_start")
        builder.adjust(1)

        await safe_edit_message(callback.message, text, reply_markup=builder.as_markup(), parse_mode="HTML")

    except Exception as e:
        chat_id = callback.message.chat.id
        logger.error(f"(C) {chat_id} - редактирование настроек: {e}")
        await safe_edit_message(callback.message, "Произошла ошибка при редактировании настроек")


@router.callback_query(F.data.startswith("chat_edit_reminder1"))
async def callback_edit_reminder1(callback: CallbackQuery, db_user):
    """Редактирование первого напоминания"""
    await callback.answer()

    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id

        # Проверяем права доступа
        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.answer(ERROR_NOT_ADMIN, show_alert=True)
            return

        # Получаем чат для определения режима
        chat = await chat_service.get_chat(chat_id)
        if not chat:
            await safe_edit_message(callback.message, "❌ Чат не найден")
            return

        # Получаем topic_id из сообщения (в multi-mode используется, в single-mode игнорируется)
        topic_id = await chat_service.get_topic_id_from_message(callback.message)

        # Получаем топик с учетом режима
        if chat.mode == "single":
            topics = await chat_service.get_chat_groups_topics(chat_id)
            chat_topic = topics[0] if topics else None
        else:
            chat_topic = await chat_service.get_chat_topic(chat_id, topic_id)

        if not chat_topic:
            await safe_edit_message(callback.message, "❌ Топик не настроен")
            return

        text = CHAT_EDIT_REMINDER_TEXT.format(
            reminder_number="1️⃣",
            reminder_name="Первое напоминание",
            offset=chat_topic.reminder1_offset,
            unit=chat_topic.reminder1_unit,
        )

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

        builder.button(
            text="✏️ Свой вариант",
            callback_data="chat_edit_custom_reminder_1"
        )
        builder.button(text="🔙 Назад", callback_data="chat_settings_from_start")
        builder.adjust(2)

        await safe_edit_message(callback.message, text, reply_markup=builder.as_markup(), parse_mode="HTML")

    except Exception as e:
        chat_id = callback.message.chat.id
        logger.error(f"(C) {chat_id} - редактирование первого напоминания: {e}")
        await safe_edit_message(callback.message, "Произошла ошибка при редактировании настроек")


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
            await callback.answer(ERROR_NOT_ADMIN, show_alert=True)
            return

        # Получаем topic_id из сообщения (в multi-mode используется, в single-mode игнорируется)
        topic_id = await chat_service.get_topic_id_from_message(callback.message)

        # Обновляем настройки
        success, message_text = await chat_service.update_chat_settings(
            chat_id, user_id, callback.bot,
            topic_id=topic_id,
            reminder1_offset=offset,
            reminder1_unit=unit
        )

        if success:
            # Перепланируем уведомления
            chat = await chat_service.get_chat(chat_id)
            if chat and chat.mode == "single":
                topics = await chat_service.get_chat_groups_topics(chat_id)
                chat_topic = topics[0] if topics else None
            else:
                chat_topic = await chat_service.get_chat_topic(chat_id, topic_id)

            if chat_topic:
                rescheduled_count = await chat_notification_scheduler_service.reschedule_notifications_for_chat_settings_update(chat_topic)
            else:
                rescheduled_count = 0

            message_text += f"\n\n🔄 Перепланировано {rescheduled_count} уведомлений"

            # Возвращаемся к интерфейсу настроек
            if chat and chat.mode == "single":
                topics = await chat_service.get_chat_groups_topics(chat_id)
                chat_topic = topics[0] if topics else None
            else:
                chat_topic = await chat_service.get_chat_topic(chat_id, topic_id)

            if chat_topic:
                await show_chat_settings_interface(callback.message, chat_topic, edit_mode=True)
        else:
            await safe_edit_message(callback.message, message_text, parse_mode="HTML")

    except Exception as e:
        chat_id = callback.message.chat.id
        logger.error(f"(C) {chat_id} - изменение первого напоминания: {e}")
        await safe_edit_message(callback.message, "Произошла ошибка при изменении настроек")


@router.callback_query(F.data.startswith("chat_edit_reminder2"))
async def callback_edit_reminder2(callback: CallbackQuery, db_user):
    """Редактирование второго напоминания"""
    await callback.answer()

    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id

        # Проверяем права доступа
        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.answer(ERROR_NOT_ADMIN, show_alert=True)
            return

        # Получаем чат для определения режима
        chat = await chat_service.get_chat(chat_id)
        if not chat:
            await safe_edit_message(callback.message, "❌ Чат не найден")
            return

        # Получаем topic_id из сообщения (в multi-mode используется, в single-mode игнорируется)
        topic_id = await chat_service.get_topic_id_from_message(callback.message)

        # Получаем топик с учетом режима
        if chat.mode == "single":
            topics = await chat_service.get_chat_groups_topics(chat_id)
            chat_topic = topics[0] if topics else None
        else:
            chat_topic = await chat_service.get_chat_topic(chat_id, topic_id)

        if not chat_topic:
            await safe_edit_message(callback.message, "❌ Топик не настроен")
            return

        text = CHAT_EDIT_REMINDER_TEXT.format(
            reminder_number="2️⃣",
            reminder_name="Второе напоминание",
            offset=chat_topic.reminder2_offset,
            unit=chat_topic.reminder2_unit,
        )

        builder = InlineKeyboardBuilder()

        # Варианты для дней
        for days in [1, 2, 3, 7]:
            builder.button(
                text=f"{days} дней",
                callback_data=f"chat_set_reminder2_{days}_days"
            )

        # Варианты для часов
        for hours in [1, 6, 12, 24]:
            builder.button(
                text=f"{hours} часов",
                callback_data=f"chat_set_reminder2_{hours}_hours"
            )

        builder.button(
            text="✏️ Свой вариант",
            callback_data="chat_edit_custom_reminder_2"
        )
        builder.button(text="🔙 Назад", callback_data="chat_settings_from_start")
        builder.adjust(2)

        await safe_edit_message(callback.message, text, reply_markup=builder.as_markup(), parse_mode="HTML")

    except Exception as e:
        chat_id = callback.message.chat.id
        logger.error(f"(C) {chat_id} - редактирование второго напоминания: {e}")
        await safe_edit_message(callback.message, "Произошла ошибка при редактировании настроек")


@router.callback_query(F.data.startswith("chat_set_reminder2_"))
async def callback_set_reminder2(callback: CallbackQuery, db_user):
    """Установка второго напоминания"""
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
            await callback.answer(ERROR_NOT_ADMIN, show_alert=True)
            return

        # Получаем чат для определения режима и topic_id
        chat = await chat_service.get_chat(chat_id)
        if not chat:
            await safe_edit_message(callback.message, "❌ Чат не найден")
            return

        # Получаем topic_id с учетом режима
        if chat.mode == "single":
            topics = await chat_service.get_chat_groups_topics(chat_id)
            topic_id = topics[0].topic_id if topics else None
        else:
            topic_id = await chat_service.get_topic_id_from_message(callback.message)

        # Обновляем настройки
        success, message_text = await chat_service.update_chat_settings(
            chat_id, user_id, callback.bot,
            topic_id=topic_id,
            reminder2_offset=offset,
            reminder2_unit=unit
        )

        if success:
            # Перепланируем уведомления
            if chat.mode == "single":
                topics = await chat_service.get_chat_groups_topics(chat_id)
                chat_topic = topics[0] if topics else None
            else:
                chat_topic = await chat_service.get_chat_topic(chat_id, topic_id)

            if chat_topic:
                rescheduled_count = await chat_notification_scheduler_service.reschedule_notifications_for_chat_settings_update(chat_topic)
            else:
                rescheduled_count = 0

            message_text += f"\n\n🔄 Перепланировано {rescheduled_count} уведомлений"

            # Возвращаемся к интерфейсу настроек
            if chat and chat.mode == "single":
                topics = await chat_service.get_chat_groups_topics(chat_id)
                chat_topic = topics[0] if topics else None
            else:
                chat_topic = await chat_service.get_chat_topic(chat_id, topic_id)

            if chat_topic:
                await show_chat_settings_interface(callback.message, chat_topic, edit_mode=True)
        else:
            await safe_edit_message(callback.message, message_text, parse_mode="HTML")

    except Exception as e:
        chat_id = callback.message.chat.id
        logger.error(f"(C) {chat_id} - изменение второго напоминания: {e}")
        await safe_edit_message(callback.message, "Произошла ошибка при изменении настроек")


@router.callback_query(F.data == "chat_toggle_active")
async def callback_toggle_chat_active(callback: CallbackQuery, db_user):
    """Переключение активности бота"""
    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        username = callback.from_user.username

        logger.info(f"(C) {chat_id} - toggle_active user=@{username or f'ID{user_id}'}")

        # Проверяем права доступа
        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.answer(ERROR_NOT_ADMIN, show_alert=True)
            return

        await callback.answer()

        # Получаем topic_id
        topic_id = await chat_service.get_topic_id_from_message(callback.message)

        # Переключаем активность топика
        success, message_text = await chat_service.toggle_chat_active(chat_id, user_id, callback.bot, topic_id)

        if success:
            # Получаем обновленный топик с учетом режима
            chat = await chat_service.get_chat(chat_id)
            if chat and chat.mode == "single":
                topics = await chat_service.get_chat_groups_topics(chat_id)
                chat_topic = topics[0] if topics else None
            else:
                chat_topic = await chat_service.get_chat_topic(chat_id, topic_id)

            if chat_topic:
                if chat_topic.is_active:
                    # Если включили — создадим уведомления для всех существующих дедлайнов дисциплины
                    with contextlib.suppress(Exception):
                        await chat_notification_scheduler_service.schedule_notifications_for_chat_subscription(
                            chat_id, chat_topic.subject_id, chat_topic=chat_topic
                        )
                else:
                    # Если выключили — отменяем все запланированные уведомления этого топика
                    with contextlib.suppress(Exception):
                        from sqlalchemy import update

                        from src.core.models import ChatScheduledNotification
                        async with db_manager.async_session() as session:
                            await session.execute(
                                update(ChatScheduledNotification)
                                .where(
                                    ChatScheduledNotification.chat_topic_id == chat_topic.id,
                                    ChatScheduledNotification.status == "scheduled"
                                )
                                .values(status="cancelled")
                            )
                            await session.commit()

                # Обновляем интерфейс настроек
                await show_chat_settings_interface(callback.message, chat_topic, edit_mode=True)
                await callback.answer(message_text, show_alert=False)
        else:
            await safe_edit_message(callback.message, message_text, parse_mode="HTML")
            await callback.answer(message_text, show_alert=True)

    except Exception as e:
        logger.error(f"(C) {chat_id} - переключение активности: {e}")
        await safe_edit_message(callback.message, "Произошла ошибка при изменении настроек")


@router.callback_query(F.data == "chat_advanced_settings")
async def callback_advanced_settings(callback: CallbackQuery, db_user):
    """Дополнительные настройки (переключение режима)"""
    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        username = callback.from_user.username

        logger.info(f"(C) {chat_id} - advanced_settings user=@{username or f'ID{user_id}'}")

        # Проверяем права доступа
        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.answer(ERROR_NOT_ADMIN, show_alert=True)
            return

        await callback.answer()

        # Получаем чат
        chat = await chat_service.get_chat(chat_id)
        if not chat:
            await safe_edit_message(callback.message, "❌ Чат не найден")
            return

        text = "⚙️ <b>Дополнительные настройки</b>\n\n"
        text += f"<b>Текущий режим:</b> {'Single-mode' if chat.mode == 'single' else 'Multi-mode'}\n\n"

        if chat.mode == "single":
            text += "В single-mode одна дисциплина на весь чат.\n\n"
            text += "При переключении в multi-mode:\n"
            text += "• Текущие настройки будут удалены\n"
            text += "• Нужно будет настроить каждый топик отдельно\n"
            new_mode = "multi"
            button_text = "🔄 Переключить чат в Multi-mode"
        else:
            text += "В multi-mode каждый топик может иметь свою дисциплину.\n\n"
            text += "При переключении в single-mode:\n"
            # Получаем список топиков
            topics = await chat_service.get_chat_groups_topics(chat_id)
            if topics:
                text += "• Будут удалены настройки для топиков:\n"
                for topic in topics:
                    topic_display = topic.topic_title or (f"ID {topic.topic_id}" if topic.topic_id else "Общий чат")
                    text += f"  - {topic_display} ({topic.subject.name})\n"
                text += "• Нужно будет настроить чат заново\n"
            new_mode = "single"
            button_text = "🔄 Переключить чат в Single-mode"

        builder = InlineKeyboardBuilder()
        builder.button(text=button_text, callback_data=f"chat_switch_mode_{new_mode}")
        builder.button(text="🔙 Назад", callback_data="chat_settings_from_start")
        builder.adjust(1)

        await safe_edit_message(callback.message, text, reply_markup=builder.as_markup(), parse_mode="HTML")

    except Exception as e:
        logger.error(f"(C) {callback.message.chat.id} - дополнительные настройки: {e}")
        await safe_edit_message(callback.message, "Произошла ошибка при открытии дополнительных настроек")


@router.callback_query(F.data.startswith("chat_switch_mode_"))
async def callback_switch_mode(callback: CallbackQuery, db_user, state: FSMContext):
    """Показ подтверждения переключения режима чата"""
    try:
        new_mode = callback.data.split("_")[-1]  # 'single' или 'multi'
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        username = callback.from_user.username

        logger.info(f"(C) {chat_id} - switch_mode_{new_mode} user=@{username or f'ID{user_id}'}")

        # Проверяем права доступа
        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.answer(ERROR_NOT_ADMIN, show_alert=True)
            return

        await callback.answer()

        # Получаем текущий чат для определения текущего режима
        chat = await chat_service.get_chat(chat_id)
        if not chat:
            await safe_edit_message(callback.message, "❌ Чат не найден")
            return

        current_mode = chat.mode
        # Определяем название режима
        mode_name = "Single-mode" if new_mode == "single" else "Multi-mode"

        # Формируем текст подтверждения в зависимости от направления переключения
        text = "🔄 <b>Переключение режима чата</b>\n\n"
        text += f"Вы хотите переключить чат в режим <b>{mode_name}</b>?\n\n"
        text += "⚠️ <b>Внимание:</b>\n"

        if current_mode == "single" and new_mode == "multi":
            # Переключение из Single-mode в Multi-mode
            text += "• Текущие настройки Single-mode будут удалены\n"
            text += "• Все уведомления будут отменены\n"
            text += "• Нужно будет настроить каждый топик отдельно\n"
        else:
            # Переключение из Multi-mode в Single-mode
            topics = await chat_service.get_chat_groups_topics(chat_id)
            topics_count = len(topics) if topics else 0
            text += "• Все привязки дисциплин к топикам будут удалены\n"
            text += "• Все уведомления будут отменены\n"
            text += "• Нужно будет настроить чат заново\n"
            if topics_count > 0:
                text += f"\n📊 Будет удалено привязок: {topics_count}"

        # Создаем кнопки подтверждения/отмены
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Подтвердить", callback_data=f"chat_confirm_switch_mode_{new_mode}")
        builder.button(text="❌ Отмена", callback_data="chat_cancel_switch_mode")
        builder.adjust(1)

        # Сохраняем режим в FSM
        await state.set_state(ChatSwitchModeStates.confirming_switch)
        await state.update_data(new_mode=new_mode, chat_id=chat_id)

        await safe_edit_message(callback.message, text, reply_markup=builder.as_markup(), parse_mode="HTML")

    except Exception as e:
        logger.error(f"(C) {callback.message.chat.id} - показ подтверждения переключения режима: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


@router.callback_query(F.data.startswith("chat_confirm_switch_mode_"))
async def callback_confirm_switch_mode(callback: CallbackQuery, db_user, state: FSMContext):
    """Подтверждение и выполнение переключения режима"""
    try:
        new_mode = callback.data.split("_")[-1]  # 'single' или 'multi'
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        username = callback.from_user.username

        logger.info(f"(C) {chat_id} - confirm_switch_mode_{new_mode} user=@{username or f'ID{user_id}'}")

        # Проверяем права доступа
        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.answer(ERROR_NOT_ADMIN, show_alert=True)
            await state.clear()
            return

        await callback.answer("Переключаю режим...")

        # Переключаем режим
        success, message_text = await chat_service.switch_chat_mode(chat_id, new_mode, user_id, callback.bot)

        if success:
            # Определяем название режима
            mode_name = "Single-mode" if new_mode == "single" else "Multi-mode"

            # Формируем текст успешного переключения
            from src.bot.texts import CHAT_SWITCH_MODE_SUCCESS
            text = CHAT_SWITCH_MODE_SUCCESS.format(mode_name=mode_name)

            # Создаем кнопки
            builder = InlineKeyboardBuilder()
            builder.button(text="⚙️ Настройки бота", callback_data="chat_settings_from_start")
            builder.button(text="❓ Помощь", callback_data="quick_help")
            builder.adjust(1)

            await safe_edit_message(callback.message, text, reply_markup=builder.as_markup(), parse_mode="HTML")
        else:
            await safe_edit_message(callback.message, f"❌ {message_text}")

        await state.clear()

    except Exception as e:
        logger.error(f"(C) {callback.message.chat.id} - подтверждение переключения режима: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)
        await state.clear()


@router.callback_query(F.data == "chat_cancel_switch_mode")
async def callback_cancel_switch_mode(callback: CallbackQuery, db_user, state: FSMContext):
    """Отмена переключения режима"""
    await callback.answer()
    await state.clear()

    # Возвращаемся к настройкам
    chat_id = callback.message.chat.id
    chat = await chat_service.get_chat(chat_id)
    if chat:
        topic_id = await chat_service.get_topic_id_from_message(callback.message)

        # В multi-mode из общего чата показываем обзор
        if chat.mode == "multi" and topic_id is None:
            await show_chat_multi_mode_overview(callback.message, chat, edit_mode=True)
        else:
            # В single-mode или multi-mode из топика - показываем настройки топика
            topics = await chat_service.get_chat_groups_topics(chat_id)
            if chat.mode == "single":
                chat_topic = topics[0] if topics else None
            else:
                topic_id = await chat_service.get_topic_id_from_message(callback.message)
                chat_topic = await chat_service.get_chat_topic(chat_id, topic_id) if topic_id else None

            if chat_topic:
                await show_chat_settings_interface(callback.message, chat_topic, edit_mode=True)
            else:
                # Топик не настроен - показываем обзор или настройки
                if chat.mode == "multi" and topic_id is None:
                    await show_chat_multi_mode_overview(callback.message, chat, edit_mode=True)
                else:
                    await show_chat_settings_interface(callback.message, None, edit_mode=True)


@router.callback_query(F.data.startswith("chat_custom_reminder_"))
async def callback_custom_reminder_setup(callback: CallbackQuery, db_user, state: FSMContext):
    """Обработчик кастомного времени в настройке бота"""
    await callback.answer()

    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id

        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.answer(ERROR_NO_PERMISSION, show_alert=True)
            return

        reminder_number = int(callback.data.split("_")[-1])

        text, buttons = build_custom_offset_prompt(reminder_number, f"chat_setup_reminder{reminder_number}")

        builder = InlineKeyboardBuilder()
        for btn_text, cb_data in buttons:
            builder.button(text=btn_text, callback_data=cb_data)

        await state.update_data(reminder_number=reminder_number, is_setup=True)
        await state.set_state(ChatSetupStates.waiting_custom_reminder)
        await safe_edit_message(callback.message, text, reply_markup=builder.as_markup(), parse_mode="HTML")

    except (ValueError, IndexError) as e:
        chat_id = callback.message.chat.id
        logger.error(f"(C) {chat_id} - настройка кастомного напоминания: {e}")
        await callback.answer("Ошибка настройки", show_alert=True)


@router.callback_query(F.data.startswith("chat_edit_custom_reminder_"))
async def callback_custom_reminder_edit(callback: CallbackQuery, db_user, state: FSMContext):
    """Обработчик кастомного времени при редактировании настроек"""
    await callback.answer()

    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id

        if not await chat_service.is_chat_admin(callback.bot, chat_id, user_id):
            await callback.answer(ERROR_NOT_ADMIN, show_alert=True)
            return

        reminder_number = int(callback.data.split("_")[-1])

        text, buttons = build_custom_offset_prompt(reminder_number, f"chat_edit_reminder{reminder_number}")

        builder = InlineKeyboardBuilder()
        for btn_text, cb_data in buttons:
            builder.button(text=btn_text, callback_data=cb_data)

        await state.update_data(reminder_number=reminder_number, is_setup=False)
        await state.set_state(ChatSettingsStates.waiting_custom_reminder)
        await safe_edit_message(callback.message, text, reply_markup=builder.as_markup(), parse_mode="HTML")

    except (ValueError, IndexError) as e:
        chat_id = callback.message.chat.id
        logger.error(f"(C) {chat_id} - редактирование кастомного напоминания: {e}")
        await callback.answer("Ошибка настройки", show_alert=True)


@router.message(ChatSetupStates.waiting_custom_reminder)
@router.message(ChatSettingsStates.waiting_custom_reminder)
async def process_custom_reminder(message: Message, db_user, state: FSMContext):
    """Обработка кастомного времени уведомления для групповых чатов"""
    try:
        data = await state.get_data()
        reminder_number = data.get("reminder_number")
        is_setup = data.get("is_setup", False)

        if not reminder_number:
            await message.answer("Ошибка: номер уведомления не найден")
            await state.clear()
            return

        chat_id = message.chat.id
        user_id = message.from_user.id

        # Проверяем права доступа
        if not await chat_service.is_chat_admin(message.bot, chat_id, user_id):
            await message.answer(ERROR_NOT_ADMIN)
            await state.clear()
            return

        value, unit, error = parse_offset_text(message.text)
        if error:
            await message.answer(error, parse_mode="HTML")
            return
        offset_value, offset_unit = value, unit

        total_hours = 0
        if offset_unit == "hours":
            total_hours = offset_value
        elif offset_unit == "days":
            total_hours = offset_value * 24

        if total_hours < 1:
            await message.answer("❌ Минимальное время уведомления - 1 час\n")
            return

        if offset_unit == "days" and offset_value > 30:
            await message.answer("❌ Максимум 30 дней")
            return
        elif offset_unit == "hours" and offset_value > 24 * 7:
            await message.answer("❌ Максимум 168 часов (неделя)")
            return

        if is_setup:
            # Настройка бота - сохраняем в состояние
            if reminder_number == 1:
                await state.update_data(reminder1_offset=offset_value, reminder1_unit=offset_unit)
            else:
                await state.update_data(reminder2_offset=offset_value, reminder2_unit=offset_unit)
            unit_text = {"days": "дн.", "hours": "ч."}.get(offset_unit, offset_unit)
            await message.answer(f"✅ Уведомление настроено: за {offset_value} {unit_text}")

            # Возвращаемся к интерфейсу настройки времени
            data = await state.get_data()
            subject_id = data.get("subject_id")
            subject = await db_manager.get_subject_by_id(subject_id)

            reminder1_offset = data.get("reminder1_offset", 7)
            reminder1_unit = data.get("reminder1_unit", "days")
            reminder2_offset = data.get("reminder2_offset", 1)
            reminder2_unit = data.get("reminder2_unit", "days")

            text = (
                TIME_SETTINGS_SELECTED_SUBJECT_TEMPLATE.format(subject_name=subject.name)
                + f"• Первое напоминание: за {reminder1_offset} {reminder1_unit}\n"
                + f"• Второе напоминание: за {reminder2_offset} {reminder2_unit}\n"
            )

            builder = InlineKeyboardBuilder()
            builder.button(text="1️⃣ Первое напоминание", callback_data="chat_setup_reminder1")
            builder.button(text="2️⃣ Второе напоминание", callback_data="chat_setup_reminder2")
            builder.button(text="✅ Завершить настройку", callback_data="chat_setup_finish", style=ButtonStyle.SUCCESS)
            builder.button(text="🔙 Назад", callback_data="chat_setup_from_start")
            builder.adjust(1)

            await message.answer(text.strip(), reply_markup=builder.as_markup(), parse_mode="HTML")
            await state.set_state(ChatSetupStates.waiting_time_settings)
        else:
            # Редактирование настроек - обновляем сразу
            # Получаем чат для определения режима и topic_id
            chat = await chat_service.get_chat(chat_id)
            if not chat:
                await message.answer("❌ Чат не найден")
                await state.clear()
                return

            # Получаем topic_id с учетом режима
            if chat.mode == "single":
                topics = await chat_service.get_chat_groups_topics(chat_id)
                topic_id = topics[0].topic_id if topics else None
            else:
                topic_id = await chat_service.get_topic_id_from_message(message)

            if reminder_number == 1:
                success, message_text = await chat_service.update_chat_settings(
                    chat_id, user_id, message.bot,
                    topic_id=topic_id,
                    reminder1_offset=offset_value,
                    reminder1_unit=offset_unit
                )
            else:
                success, message_text = await chat_service.update_chat_settings(
                    chat_id, user_id, message.bot,
                    topic_id=topic_id,
                    reminder2_offset=offset_value,
                    reminder2_unit=offset_unit
                )

            if success:
                # Перепланируем уведомления
                if chat.mode == "single":
                    topics = await chat_service.get_chat_groups_topics(chat_id)
                    chat_topic = topics[0] if topics else None
                else:
                    chat_topic = await chat_service.get_chat_topic(chat_id, topic_id)

                if chat_topic:
                    rescheduled_count = await chat_notification_scheduler_service.reschedule_notifications_for_chat_settings_update(chat_topic)
                else:
                    rescheduled_count = 0

                unit_text = {"days": "дн.", "hours": "ч."}.get(offset_unit, offset_unit)
                await message.answer(
                    f"✅ Уведомление настроено: за {offset_value} {unit_text}\n"
                    f"🔄 Перепланировано {rescheduled_count} уведомлений"
                )

                # Возвращаемся к интерфейсу настроек
                if chat.mode == "single":
                    topics = await chat_service.get_chat_groups_topics(chat_id)
                    chat_topic = topics[0] if topics else None
                else:
                    chat_topic = await chat_service.get_chat_topic(chat_id, topic_id)

                if chat_topic:
                    await show_chat_settings_interface(message, chat_topic, edit_mode=False)
            else:
                await message.answer(f"❌ {message_text}")

            await state.clear()

    except Exception as e:
        chat_id = message.chat.id
        logger.error(f"(C) {chat_id} - обработка кастомного времени: {e}")
        await message.answer("Произошла ошибка. Попробуйте еще раз.")
        await state.clear()



def register_group_chat_handlers(dp):
    """Регистрация обработчиков для групповых чатов"""
    dp.include_router(router)



async def _compose_start_info_text(chat_id: int, topic_id: int | None = None) -> str | None:
    """Собирает HTML-текст со ссылками по предмету (без дедлайнов) для чата."""
    # Получаем чат для определения режима
    chat = await chat_service.get_chat(chat_id)
    if not chat:
        return None

    # В single-mode игнорируем topic_id и получаем единственный топик
    if chat.mode == "single":
        # В single-mode получаем единственный топик (независимо от topic_id)
        topics = await chat_service.get_chat_groups_topics(chat_id)
        if not topics:
            return None
        chat_topic = topics[0]  # Берем первый (и единственный) топик
    else:
        # В multi-mode используем topic_id
        chat_topic = await chat_service.get_chat_topic(chat_id, topic_id)
        if not chat_topic:
            return None

    subject = chat_topic.subject
    lines: list[str] = []
    lines.append(f"🔹 <b>{subject.name}</b>\n\n")
    if getattr(subject, "wiki_url", None):
        lines.append(f'• <a href="{subject.wiki_url}">ФКН Wiki</a>\n')
    if getattr(subject, "vk_playlist_url", None):
        lines.append(f'• <a href="{subject.vk_playlist_url}">VK Video</a>\n')
    if getattr(subject, "yt_playlist_url", None):
        lines.append(f'• <a href="{subject.yt_playlist_url}">YouTube</a>\n')
    # lines.append("\n<i>P.S. Воспользуйтесь /info для быстрого получения дедлайнов в чате</i>")

    return "".join(lines).strip()


async def _compose_info_text(chat_id: int, topic_id: int | None = None) -> str | None:
    """Собирает HTML-текст информации о предмете и дедлайнах для чата."""
    # Получаем чат для определения режима
    chat = await chat_service.get_chat(chat_id)
    if not chat:
        return None

    # В single-mode игнорируем topic_id и получаем единственный топик
    if chat.mode == "single":
        # В single-mode получаем единственный топик (независимо от topic_id)
        topics = await chat_service.get_chat_groups_topics(chat_id)
        if not topics:
            return None
        chat_topic = topics[0]  # Берем первый (и единственный) топик
    else:
        # В multi-mode используем topic_id
        chat_topic = await chat_service.get_chat_topic(chat_id, topic_id)
        if not chat_topic:
            return None

    subject = chat_topic.subject
    lines: list[str] = []
    lines.append("<b>Информация о предмете:</b>\n\n")
    lines.append(f"🔹 <b>{subject.name}</b>")

    # Добавляем ссылки, если они есть
    if getattr(subject, "wiki_url", None):
        lines.append(f'\n• <a href="{subject.wiki_url}">ФКН Wiki</a>')
    if getattr(subject, "vk_playlist_url", None):
        lines.append(f'\n• <a href="{subject.vk_playlist_url}">VK Video</a>')
    if getattr(subject, "yt_playlist_url", None):
        lines.append(f'\n• <a href="{subject.yt_playlist_url}">YouTube</a>')

    lines.append("\n\n<b>Актуальные дедлайны:</b>\n")

    from datetime import UTC, datetime

    from sqlalchemy import and_, or_, select
    async with db_manager.async_session() as session:
        now = datetime.now(UTC)
        stmt = (
            select(Task)
            .where(
                and_(
                    Task.subject_id == subject.id,
                    or_(
                        and_(Task.soft_deadline_ts.isnot(None), Task.soft_deadline_ts >= now),
                        and_(Task.hard_deadline_ts.isnot(None), Task.hard_deadline_ts >= now),
                    ),
                )
            )
            .order_by(Task.soft_deadline_ts.nulls_last(), Task.hard_deadline_ts.nulls_last())
        )
        result = await session.execute(stmt)
        tasks = list(result.scalars().all())

    import pytz
    pytz.timezone("Europe/Moscow")

    if not tasks:
        lines.append("Актуальных дедлайнов нет.\n")
    else:
        now = datetime.now(UTC)
        for idx, d in enumerate(tasks, 1):
            hw = d.hw_name or "Без названия"
            if d.source_link:
                lines.append(f'\n<b>{idx}. <a href="{d.source_link}">{hw}</a></b>\n')
            else:
                lines.append(f"\n<b>{idx}. {hw}</b>\n")

            from src.utils.notification_formatting import (
                format_deadline_datetime,
                format_time_remaining,
            )

            def add_dt(ts, icon):
                date_str = format_deadline_datetime(ts, "Europe/Moscow")
                suffix = format_time_remaining(ts, now)
                lines.append(f"{icon} {date_str} {suffix}\n")

            if d.soft_deadline_ts and d.soft_deadline_ts >= now:
                add_dt(d.soft_deadline_ts, "🟡")
            if d.hard_deadline_ts and d.hard_deadline_ts >= now:
                add_dt(d.hard_deadline_ts, "🔴")

    # Добавляем надпись в конце сообщения
    from src.bot.texts import CHAT_DEADLINE_FOOTER
    lines.append(CHAT_DEADLINE_FOOTER)

    return "".join(lines).strip()


@router.message(and_f(Command("start_info"), F.chat.type.in_(["group", "supergroup"])))
async def cmd_chat_start_info(message: Message, db_user):
    """Показать только ссылки по предмету (без дедлайнов)"""
    try:
        chat_id = message.chat.id
        user_id = message.from_user.id
        username = message.from_user.username

        logger.info(f"(C) {chat_id} - /start_info user=@{username or f'ID{user_id}'}")

        # Получаем topic_id если команда вызвана в топике
        topic_id = await chat_service.get_topic_id_from_message(message)

        text = await _compose_start_info_text(chat_id, topic_id)
        if text is None:
            await message.answer(
                CHAT_NOT_CONFIGURED
            )
            return
        await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception:
        raise


@router.message(and_f(Command("info"), F.chat.type.in_(["group", "supergroup"])))
async def cmd_chat_info(message: Message, db_user):
    """Показать текущую дисциплину и актуальные дедлайны чата"""
    try:
        chat_id = message.chat.id
        user_id = message.from_user.id
        username = message.from_user.username

        logger.info(f"(C) {chat_id} - /info user=@{username or f'ID{user_id}'}")

        # Получаем topic_id если команда вызвана в топике
        topic_id = await chat_service.get_topic_id_from_message(message)

        text = await _compose_info_text(chat_id, topic_id)
        if text is None:
            await message.answer(
                CHAT_NOT_CONFIGURED
            )
            return
        await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception:
        raise


@router.callback_query(F.data == "chat_info")
async def callback_chat_info(callback: CallbackQuery, db_user):
    """Кнопка Информация – обновляет текущее сообщение (edit)"""
    await callback.answer()
    try:
        chat_id = callback.message.chat.id
        # Получаем topic_id если команда вызвана в топике
        topic_id = await chat_service.get_topic_id_from_message(callback.message)

        text = await _compose_info_text(chat_id, topic_id)
        if text is None:
            await safe_edit_message(
                callback.message,
                CHAT_NOT_CONFIGURED
            )
            return
        await safe_edit_message(callback.message, text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        chat_id = callback.message.chat.id
        logger.error(f"(C) {chat_id} - информация о чате: {e}")
        await callback.answer("Ошибка при получении информации", show_alert=True)
