import os

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.bot.services.admin_service import admin_service
from src.bot.services.notification_sender import notification_sender
from src.bot.texts import (
    ADMIN_BROADCAST_CONFIRM,
    ADMIN_BROADCAST_PREVIEW,
    ADMIN_BROADCAST_RESULT,
    ADMIN_CHAT_LIST_EMPTY,
    ADMIN_CHAT_LIST_HEADER,
    ADMIN_CHAT_LIST_SUMMARY,
    ADMIN_CHAT_MANAGEMENT,
    ADMIN_CHAT_TOGGLE_CONFIRM,
    ADMIN_PANEL_TITLE,
    ADMIN_STATS_CHATS,
    ADMIN_STATS_DEADLINES_ACTIVE,
    ADMIN_STATS_DEADLINES_NO_TOTAL,
    ADMIN_STATS_NOTIFICATIONS,
    ADMIN_STATS_POPULAR_SUBJECTS,
    ADMIN_STATS_SUBSCRIPTIONS,
    ADMIN_STATS_SYSTEM,
    ADMIN_STATS_TITLE,
    ADMIN_STATS_USERS_ACTIVE,
    ADMIN_STATS_USERS_NO_TOTAL,
    ADMIN_SYNC_ERROR,
    ADMIN_SYNC_ERROR_GENERIC,
    ADMIN_SYNC_SUCCESS,
    ERROR_BROADCAST_EXECUTE,
    ERROR_BROADCAST_PREPARE,
    ERROR_CHAT_LIST,
    ERROR_CHAT_MANAGEMENT,
    ERROR_CHAT_STATS,
    ERROR_CHAT_TOGGLE,
    ERROR_NO_ADMIN_RIGHTS,
    ERROR_STATS,
    ERROR_TRY_AGAIN,
)
from src.core.database import db_manager
from src.core.sync.data_syncer import data_syncer
from src.utils import get_logger, safe_edit_message
from src.utils.notification_formatting import format_duration


logger = get_logger()
router = Router()

ADMINS = []
try:
    admins_str = os.getenv("ADMINS", "[]")
    admins_str = admins_str.strip("[]")
    if admins_str:
        ADMINS = [int(admin_id.strip()) for admin_id in admins_str.split(",")]
except Exception as e:
    logger.error(f"[SYSTEM] Ошибка парсинга списка админов: {e}")


class BroadcastStates(StatesGroup):
    waiting_message = State()
    confirming_broadcast = State()


def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь админом"""
    return user_id in ADMINS


async def show_statistics(message_or_callback, db_user, show_back_button: bool = False):
    """Общая функция для отображения статистики"""
    try:
        stats = await admin_service.get_bot_statistics()
        text = await format_statistics_message(stats)

        # Создаем клавиатуру с дополнительными действиями
        builder = InlineKeyboardBuilder()
        builder.button(
            text="🔄 Обновить статистику", callback_data="admin_refresh_stats"
        )

        if show_back_button:
            builder.button(text="🔙 Назад к админ-панели", callback_data="admin_panel")
            builder.adjust(1, 1, 1)
        else:
            builder.adjust(1, 1)

        if isinstance(message_or_callback, CallbackQuery):
            await safe_edit_message(
                message_or_callback.message, text, reply_markup=builder.as_markup()
            )
        else:
            await message_or_callback.answer(text, reply_markup=builder.as_markup())

        logger.info(f"(A) {db_user.tg_user_id} - Статистика")

    except Exception as e:
        logger.error(f"(A) {db_user.tg_user_id} - получение статистики: {e}")
        error_text = ERROR_STATS

        if show_back_button:
            error_keyboard = (
                InlineKeyboardBuilder()
                .button(text="🔙 Назад", callback_data="admin_panel")
                .as_markup()
            )
        else:
            error_keyboard = None

        if isinstance(message_or_callback, CallbackQuery):
            await safe_edit_message(
                message_or_callback.message, error_text, reply_markup=error_keyboard
            )
        else:
            await message_or_callback.answer(error_text)


async def perform_sync(message_or_callback, db_user, show_back_button: bool = False):
    """Общая функция для выполнения синхронизации"""
    try:
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.answer("Запускаю синхронизацию...")

        logger.info(f"(A) {db_user.tg_user_id} - Синхронизация")
        sync_result = await data_syncer.sync_data()
        success = (
            bool(sync_result.get("success"))
            if isinstance(sync_result, dict)
            else bool(sync_result)
        )

        if success:
            text = ADMIN_SYNC_SUCCESS
            try:
                # Отправка мгновенных уведомлений об изменениях при ручной синхронизации
                if isinstance(sync_result, dict):
                    changes = sync_result.get("changes", [])
                    if changes:
                        bot = message_or_callback.bot
                        await notification_sender.send_immediate_task_changes(
                            bot, changes
                        )
                        logger.info(
                            f"Отправлены мгновенные уведомления об изменениях: {len(changes)} дедлайнов"
                        )
            except Exception as e:
                logger.warning(
                    f"Ошибка отправки мгновенных уведомлений при ручной синхронизации: {e}"
                )
        else:
            text = ADMIN_SYNC_ERROR

        if show_back_button:
            builder = InlineKeyboardBuilder()
            builder.button(text="🔙 Назад к админ-панели", callback_data="admin_panel")
            keyboard = builder.as_markup()
        else:
            keyboard = None

        if isinstance(message_or_callback, CallbackQuery):
            await safe_edit_message(message_or_callback.message, text, reply_markup=keyboard)
        else:
            # Для команды /fast_sync статусное сообщение редактируем напрямую
            await safe_edit_message(message_or_callback, text)

        logger.info(
            f"Синхронизация завершена. Результат: {'успех' if success else 'ошибка'}"
        )

    except Exception as e:
        logger.error(f"(A) {db_user.tg_user_id} - выполнение синхронизации: {e}")
        error_text = ADMIN_SYNC_ERROR_GENERIC

        if show_back_button:
            error_keyboard = (
                InlineKeyboardBuilder()
                .button(text="🔙 Назад", callback_data="admin_panel")
                .as_markup()
            )
        else:
            error_keyboard = None

        if isinstance(message_or_callback, CallbackQuery):
            await safe_edit_message(
                message_or_callback.message, error_text, reply_markup=error_keyboard
            )
        else:
            await message_or_callback.answer(
                f"❌ Ошибка при выполнении синхронизации: {e!s}"
            )


async def format_statistics_message(stats: dict) -> str:
    """Форматирование сообщения со статистикой"""
    text = ADMIN_STATS_TITLE

    # Пользователи
    total_users = stats.get("total_users", 0)
    active_day = stats.get("active_users_day", 0)
    active_week = stats.get("active_users_week", 0)
    active_month = stats.get("active_users_month", 0)

    if total_users > 0:
        day_pct = (active_day / total_users) * 100
        week_pct = (active_week / total_users) * 100
        month_pct = (active_month / total_users) * 100
        text += ADMIN_STATS_USERS_ACTIVE.format(
            total_users=total_users,
            active_day=active_day,
            day_pct=day_pct,
            active_week=active_week,
            week_pct=week_pct,
            active_month=active_month,
            month_pct=month_pct,
        )
    else:
        text += ADMIN_STATS_USERS_NO_TOTAL.format(
            total_users=total_users,
            active_day=active_day,
            active_week=active_week,
            active_month=active_month,
        )

    # Статистика подписок
    total_subscriptions = stats.get("total_subscriptions", 0)
    users_with_subs = stats.get("users_with_subscriptions", 0)

    text += ADMIN_STATS_SUBSCRIPTIONS.format(
        total_subscriptions=total_subscriptions,
        users_with_subs=users_with_subs,
    )

    # Статистика групповых чатов
    text += ADMIN_STATS_CHATS.format(total_chats=stats.get("total_chats", 0))

    # Популярные предметы
    popular_subjects = stats.get("popular_subjects", [])
    if popular_subjects:
        popular_list = "\n".join(
            f"{i}. {subject_name} ({count})"
            for i, (subject_name, count) in enumerate(popular_subjects[:5], 1)
        )
        text += ADMIN_STATS_POPULAR_SUBJECTS.format(popular_list=popular_list)

    # Статистика дедлайнов
    total_deadlines = stats.get("total_deadlines", 0)
    active_deadlines = stats.get("active_deadlines", 0)

    if total_deadlines > 0:
        active_pct = (active_deadlines / total_deadlines) * 100
        text += ADMIN_STATS_DEADLINES_ACTIVE.format(
            total_deadlines=total_deadlines,
            active_deadlines=active_deadlines,
            active_pct=active_pct,
        )
    else:
        text += ADMIN_STATS_DEADLINES_NO_TOTAL.format(
            total_deadlines=total_deadlines,
            active_deadlines=active_deadlines,
        )

    # Статистика уведомлений
    personal_notifs = stats.get("scheduled_notifications", 0)
    chat_notifs = stats.get("scheduled_chat_notifications", 0)
    total_notifs = personal_notifs + chat_notifs

    text += ADMIN_STATS_NOTIFICATIONS.format(
        total_notifs=total_notifs,
        personal_notifs=personal_notifs,
        chat_notifs=chat_notifs,
    )

    # Системная информация
    text += ADMIN_STATS_SYSTEM.format(last_sync=stats.get("last_sync", "Неизвестно"))

    return text


@router.message(Command("logs"))
async def cmd_logs(message: Message, db_user):
    """Обработчик команды /logs - получение логов для админов"""
    if not is_admin(db_user.tg_user_id):
        await message.answer(ERROR_NO_ADMIN_RIGHTS)
        return

    try:
        logger.info(f"(A) {db_user.tg_user_id} - Логи")
        await admin_service.send_logs_to_admin(message.bot, db_user.tg_user_id)

    except Exception as e:
        logger.error(f"(A) {db_user.tg_user_id} - команда /logs: {e}")
        await message.answer(f"❌ Ошибка при получении логов: {e!s}")


@router.message(Command("fast_sync"))
async def cmd_fast_sync(message: Message, db_user):
    """Обработчик команды /fast_sync - быстрая синхронизация для админов"""
    if not is_admin(db_user.tg_user_id):
        await message.answer(ERROR_NO_ADMIN_RIGHTS)
        return

    # Создаем статусное сообщение
    status_message = await message.answer("🔄 <b>Запускаю синхронизацию...</b>")

    # Используем общую функцию синхронизации
    await perform_sync(status_message, db_user, show_back_button=False)


@router.message(Command("stats"))
async def cmd_stats(message: Message, db_user):
    """Обработчик команды /stats - статистика для админов"""
    if not is_admin(db_user.tg_user_id):
        await message.answer(ERROR_NO_ADMIN_RIGHTS)
        return

    # Используем общую функцию отображения статистики
    await show_statistics(message, db_user, show_back_button=False)


@router.message(Command("broadcast"))
@router.callback_query(F.data == "admin_broadcast")
async def cmd_broadcast(event: Message | CallbackQuery, db_user, state: FSMContext):
    """Обработчик команды /broadcast - массовая рассылка"""
    if isinstance(event, CallbackQuery):
        await event.answer()
        message = event.message
    else:
        message = event

    if not is_admin(db_user.tg_user_id):
        await message.answer(ERROR_NO_ADMIN_RIGHTS)
        return

    try:
        # Получаем количество пользователей для рассылки
        user_count = await admin_service.get_users_count()

        text = ADMIN_BROADCAST_CONFIRM.format(user_count=user_count)

        builder = InlineKeyboardBuilder()
        builder.button(text="❌ Отмена", callback_data="admin_cancel_broadcast")

        await state.set_state(BroadcastStates.waiting_message)
        await message.answer(text, reply_markup=builder.as_markup())

    except Exception as e:
        logger.error(f"(A) {db_user.tg_user_id} - команда /broadcast: {e}")
        await message.answer(ERROR_BROADCAST_PREPARE)


@router.message(BroadcastStates.waiting_message)
async def process_broadcast_message(message: Message, db_user, state: FSMContext):
    """Обработка сообщения для рассылки"""
    if not is_admin(db_user.tg_user_id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        await state.clear()
        return

    try:
        # Сохраняем сообщение для рассылки
        await state.update_data(
            broadcast_text=message.html_text, broadcast_entities=message.entities
        )

        user_count = await admin_service.get_users_count()

        message_preview = f"{message.html_text[:500]}{'...' if len(message.html_text) > 500 else ''}"
        text = ADMIN_BROADCAST_PREVIEW.format(
            user_count=user_count, message_preview=message_preview
        )

        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Отправить", callback_data="admin_confirm_broadcast")
        builder.button(text="❌ Отмена", callback_data="admin_cancel_broadcast")
        builder.adjust(2)

        await state.set_state(BroadcastStates.confirming_broadcast)
        await message.answer(text, reply_markup=builder.as_markup())

    except Exception as e:
        user_id = message.from_user.id if message.from_user else 0
        logger.error(f"(A) {user_id} - обработка сообщения для рассылки: {e}")
        await message.answer(ERROR_TRY_AGAIN)


@router.callback_query(F.data == "admin_confirm_broadcast")
async def callback_confirm_broadcast(
    callback: CallbackQuery, db_user, state: FSMContext
):
    """Подтверждение и выполнение рассылки"""
    if not is_admin(db_user.tg_user_id):
        await callback.answer("❌ Нет прав доступа", show_alert=True)
        return

    await callback.answer("Запускаю рассылку...")

    try:
        data = await state.get_data()
        broadcast_text = data.get("broadcast_text")
        broadcast_entities = data.get("broadcast_entities")

        if not broadcast_text:
            await safe_edit_message(callback.message, "❌ Сообщение для рассылки не найдено.")
            await state.clear()
            return

        # Запускаем рассылку
        result = await admin_service.send_broadcast(
            broadcast_text,
            callback.bot,
            broadcast_entities=broadcast_entities,
        )

        success_count = result.get("success", 0)
        error_count = result.get("errors", 0)
        duration = result.get("duration", 0.0)
        total_count = success_count + error_count
        duration_str = format_duration(duration)

        error_note = (
            "\n\n<i>Ошибки могут возникать из-за заблокированных ботов или удаленных аккаунтов.</i>"
            if error_count > 0
            else ""
        )

        result_text = ADMIN_BROADCAST_RESULT.format(
            success_count=success_count,
            error_count=error_count,
            total_count=total_count,
            duration=duration_str,
            error_note=error_note,
        )

        await safe_edit_message(callback.message, result_text)
        await state.clear()

        logger.info(
            f"Админ {db_user.tg_user_id} выполнил рассылку: {success_count}/{total_count}, "
            f"за {duration_str}"
        )

    except Exception as e:
        logger.error(f"(A) {db_user.tg_user_id} - выполнение рассылки: {e}")
        await safe_edit_message(callback.message, ERROR_BROADCAST_EXECUTE)
        await state.clear()


@router.callback_query(F.data == "admin_cancel_broadcast")
async def callback_cancel_broadcast(
    callback: CallbackQuery, db_user, state: FSMContext
):
    """Отмена рассылки"""
    await callback.answer()
    await state.clear()
    # Просто возвращаемся в админ-панель без сообщения об отмене
    await callback_admin_panel(callback, db_user)


@router.callback_query(F.data == "admin_panel")
async def callback_admin_panel(callback: CallbackQuery, db_user):
    """Обработчик админ-панели"""
    if not is_admin(db_user.tg_user_id):
        await callback.answer("❌ Нет прав доступа", show_alert=True)
        return

    await callback.answer()

    text = ADMIN_PANEL_TITLE

    builder = InlineKeyboardBuilder()

    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="📄 Логи", callback_data="admin_logs")

    builder.button(text="🔄 Sync - Дедлайны", callback_data="admin_sync")
    builder.button(text="🔄 Sync - Дисциплины", callback_data="admin_sync_subjects")

    builder.row()
    builder.button(text="📢 Broadcast", callback_data="admin_broadcast")
    builder.button(text="💬 Управление чатами", callback_data="admin_chat_management")

    builder.row()
    builder.button(text="🔙 Назад", callback_data="back_to_menu")
    builder.adjust(2, 2)

    await safe_edit_message(callback.message, text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "admin_stats")
async def callback_admin_stats(callback: CallbackQuery, db_user):
    """Обработчик кнопки статистики в админ-панели"""
    if not is_admin(db_user.tg_user_id):
        await callback.answer("❌ Нет прав доступа", show_alert=True)
        return

    await callback.answer("Загружаю статистику...")

    # Используем общую функцию отображения статистики
    await show_statistics(callback, db_user, show_back_button=True)


@router.callback_query(F.data == "admin_logs")
async def callback_admin_logs(callback: CallbackQuery, db_user):
    """Обработчик отправки логов"""
    if not is_admin(db_user.tg_user_id):
        await callback.answer("❌ Нет прав доступа", show_alert=True)
        return

    await callback.answer("Подготавливаю логи...")

    try:
        # Отправляем логи (файлы отправляются отдельными сообщениями)
        success = await admin_service.send_logs_to_admin(
            callback.bot, db_user.tg_user_id
        )

        # Не редактируем сообщение, так как логи отправляются отдельно
        # Просто показываем уведомление
        if success:
            await callback.answer("✅ Логи отправлены", show_alert=True)
        else:
            await callback.answer("❌ Логи не найдены", show_alert=True)

    except Exception as e:
        user_id = callback.from_user.id if callback.from_user else 0
        logger.error(f"(A) {user_id} - отправка логов: {e}")
        await callback.answer(f"❌ Ошибка: {e!s}", show_alert=True)


@router.callback_query(F.data == "admin_refresh_stats")
async def callback_admin_refresh_stats(callback: CallbackQuery, db_user):
    """Обработчик кнопки обновления статистики"""
    if not is_admin(db_user.tg_user_id):
        await callback.answer("❌ Нет прав доступа", show_alert=True)
        return

    await callback.answer("Обновляю статистику...")

    # Используем общую функцию отображения статистики
    await show_statistics(callback, db_user, show_back_button=True)


@router.callback_query(F.data == "admin_sync")
async def callback_admin_sync(callback: CallbackQuery, db_user):
    """Обработчик мгновенной синхронизации"""
    if not is_admin(db_user.tg_user_id):
        await callback.answer("❌ Нет прав доступа", show_alert=True)
        return

    # Используем общую функцию синхронизации
    await perform_sync(callback, db_user, show_back_button=True)


@router.callback_query(F.data == "admin_sync_subjects")
async def callback_admin_sync_subjects(callback: CallbackQuery, db_user):
    """Ручная синхронизация дисциплин (для админов)."""
    if not is_admin(db_user.tg_user_id):
        await callback.answer("❌ Нет прав доступа", show_alert=True)
        return

    try:
        await callback.answer("Запускаю синхронизацию дисциплин...")
        result = await data_syncer.sync_subjects()
        updated = result.get("updated", 0)
        created = result.get("created", 0)
        text = (
            "✅ <b>Синхронизация дисциплин завершена</b>\n\n"
            f"Обновлено: {updated}\nСоздано: {created}"
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 Назад к админ-панели", callback_data="admin_panel")
        await safe_edit_message(callback.message, text, reply_markup=builder.as_markup(), parse_mode="HTML")
    except Exception as e:
        user_id = callback.from_user.id if callback.from_user else 0
        logger.error(f"(A) {user_id} - синхронизация дисциплин: {e}")
        await safe_edit_message(callback.message, "❌ Ошибка при синхронизации дисциплин", parse_mode="HTML")


@router.message(Command("chat_stats"))
async def cmd_chat_stats(message: Message, db_user):
    """Команда статистики по чатам"""
    if not is_admin(db_user.tg_user_id):
        await message.answer(ERROR_NO_ADMIN_RIGHTS)
        return

    try:
        from src.bot.services.chat_service import chat_service

        logger.info(f"(A) {db_user.tg_user_id} - Запрос статистики по чатам")

        # Получаем статистику по чатам
        total_chats = await chat_service.get_chat_groups_count()
        active_chats = await chat_service.get_active_chat_groups_count()
        chat_groups = await chat_service.get_all_chat_groups()
        inactive_chats = max(total_chats - active_chats, 0)

        text = "📊 <b>Статистика по чатам</b>\n\n"
        text += "📈 <b>Общая статистика:</b>\n"
        text += f"• Всего настроенных чатов: {total_chats}\n"
        text += f"• Активных чатов: {active_chats}\n"
        text += f"• Неактивных чатов: {inactive_chats}\n\n"

        if chat_groups:
            text += "📋 <b>Список чатов:</b>\n"
            for chat_group in chat_groups[:10]:  # Показываем первые 10
                status_emoji = "✅" if chat_group.is_active else "❌"
                topic_info = f" (топик {chat_group.topic_id})" if chat_group.topic_id else " (общий чат)"
                text += f"{status_emoji} {chat_group.subject.name}{topic_info}\n"

            if len(chat_groups) > 10:
                text += f"... и еще {len(chat_groups) - 10} чатов\n"

        await message.answer(text, parse_mode="HTML")

    except Exception as e:
        logger.error(f"(A) {db_user.tg_user_id} - команда /chat_stats: {e}")
        await message.answer(ERROR_CHAT_STATS)


@router.callback_query(F.data == "admin_chat_management")
async def callback_admin_chat_management(callback: CallbackQuery, db_user):
    """Обработчик кнопки управления чатами"""
    if not is_admin(db_user.tg_user_id):
        await callback.answer("❌ Нет прав доступа", show_alert=True)
        return

    await callback.answer()

    try:
        from src.bot.services.chat_service import chat_service

        logger.info(f"(A) {db_user.tg_user_id} - Открытие управления чатами")

        # Получаем статистику по чатам
        total_chats = await chat_service.get_chat_groups_count()
        active_chats = await chat_service.get_active_chat_groups_count()
        inactive_chats = max(total_chats - active_chats, 0)

        text = ADMIN_CHAT_MANAGEMENT.format(
            total_chats=total_chats,
            active_chats=active_chats,
            inactive_chats=inactive_chats,
        )

        builder = InlineKeyboardBuilder()
        builder.button(text="📋 Список чатов", callback_data="admin_chat_list")

        # Определяем текст кнопки toggle на основе статуса
        if active_chats == 0 and total_chats > 0:
            toggle_text = "🔔 Включить все"
        elif active_chats == total_chats and total_chats > 0:
            toggle_text = "🔕 Отключить все"
        else:
            toggle_text = "🔄 Инвертировать статус"

        builder.button(text=toggle_text, callback_data="admin_chat_toggle_confirm")
        builder.button(text="🔙 Назад", callback_data="admin_panel")
        builder.adjust(1)

        await safe_edit_message(callback.message, text, reply_markup=builder.as_markup(), parse_mode="HTML")

    except Exception as e:
        user_id = callback.from_user.id if callback.from_user else 0
        logger.error(f"(A) {user_id} - управление чатами: {e}")
        await safe_edit_message(callback.message, ERROR_CHAT_MANAGEMENT)


@router.callback_query(F.data == "admin_chat_list")
async def callback_admin_chat_list(callback: CallbackQuery, db_user):
    """Обработчик кнопки списка чатов"""
    if not is_admin(db_user.tg_user_id):
        await callback.answer("❌ Нет прав доступа", show_alert=True)
        return

    await callback.answer("Загружаю список чатов...")

    try:
        from src.bot.services.chat_service import chat_service

        logger.info(f"(A) {db_user.tg_user_id} - Запрос списка чатов")

        # Получаем все чаты с загруженными предметами
        chat_groups = await chat_service.get_all_chat_groups()

        if not chat_groups:
            text = ADMIN_CHAT_LIST_EMPTY
        else:
            # Формируем детальный список
            unique_chats = {cg.chat_id for cg in chat_groups}
            text = ADMIN_CHAT_LIST_HEADER.format(total_count=len(unique_chats))
            text += f"Всего топиков: <b>{len(chat_groups)}</b>\n\n"

            # Группируем по предметам для удобства
            by_subject = {}
            for chat_group in chat_groups:
                subject_name = chat_group.subject.name
                if subject_name not in by_subject:
                    by_subject[subject_name] = []
                by_subject[subject_name].append(chat_group)

            # Выводим чаты сгруппированными по предметам
            for subject_name, chats in sorted(by_subject.items()):
                text += f"🔹 <b>{subject_name}</b> ({len(chats)}):\n"
                for chat_group in chats:
                    # Формируем ссылку на чат: https://t.me/c/+ chat_id без префикса -100
                    # Для чатов с ID вида -1001234567890 нужно убрать первые 4 символа
                    chat_link_id = str(chat_group.chat_id)
                    if chat_link_id.startswith("-100"):
                        chat_link_id = chat_link_id[4:]  # Убираем "-100"
                    chat_url = f"https://t.me/c/{chat_link_id}"

                    # Показываем название чата если есть
                    chat_title = (
                        chat_group.chat_group.chat_title if chat_group.chat_group else None
                    ) or "Название недоступно"

                    # Показываем топик если есть
                    if chat_group.topic_id and chat_group.topic_title:
                        topic_info = f"Топик: {chat_group.topic_title}"
                    elif chat_group.topic_id:
                        topic_info = f"Топик: {chat_group.topic_id}"
                    else:
                        topic_info = "Топик: общий чат"

                    text += f'• <a href="{chat_url}">{chat_title}</a> ({topic_info})\n'
                text += "\n"

                if len(text) > 3500:
                    text += "...\n<i>(Список обрезан для предотвращения переполнения)</i>"
                    break

            # Добавляем краткую статистику
            active_chat_ids = {cg.chat_id for cg in chat_groups if cg.is_active}
            active_count = len(active_chat_ids)
            inactive_count = max(len(unique_chats) - active_count, 0)
            text += ADMIN_CHAT_LIST_SUMMARY.format(
                active_count=active_count,
                inactive_count=inactive_count,
            )

        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 Назад", callback_data="admin_chat_management")

        await safe_edit_message(callback.message, text, reply_markup=builder.as_markup(), parse_mode="HTML")

    except Exception as e:
        user_id = callback.from_user.id if callback.from_user else 0
        logger.error(f"(A) {user_id} - список чатов: {e}")
        await safe_edit_message(callback.message, ERROR_CHAT_LIST)


@router.callback_query(F.data == "admin_chat_toggle_confirm")
async def callback_admin_chat_toggle_confirm(callback: CallbackQuery, db_user):
    """Подтверждение переключения статуса всех чатов"""
    if not is_admin(db_user.tg_user_id):
        await callback.answer("❌ Нет прав доступа", show_alert=True)
        return

    await callback.answer()

    try:
        from src.bot.services.chat_service import chat_service

        # Получаем все чаты
        chat_groups = await chat_service.get_all_chat_groups()

        if not chat_groups:
            await safe_edit_message(callback.message, "❌ Нет настроенных чатов")
            return

        # Определяем действие на основе первого чата
        first_chat = chat_groups[0]
        new_status = not first_chat.is_active
        action_text = "включить" if new_status else "отключить"

        text = ADMIN_CHAT_TOGGLE_CONFIRM.format(
            action_text=action_text, chat_count=len(chat_groups)
        )

        builder = InlineKeyboardBuilder()
        builder.button(text=f"✅ {action_text.title()}", callback_data=f"admin_chat_toggle_all_{new_status}")
        builder.button(text="❌ Отмена", callback_data="admin_chat_management")
        builder.adjust(1)

        await safe_edit_message(callback.message, text, reply_markup=builder.as_markup(), parse_mode="HTML")

    except Exception as e:
        user_id = callback.from_user.id if callback.from_user else 0
        logger.error(f"(A) {user_id} - подтверждение toggle: {e}")
        await safe_edit_message(callback.message, ERROR_CHAT_TOGGLE)


@router.message(Command("chat_toggle_all"))
async def cmd_chat_toggle_all(message: Message, db_user):
    """Команда массового переключения активности чатов"""
    if not is_admin(db_user.tg_user_id):
        await message.answer(ERROR_NO_ADMIN_RIGHTS)
        return

    try:
        from src.bot.services.chat_service import chat_service

        # Получаем все чаты
        chat_groups = await chat_service.get_all_chat_groups()

        if not chat_groups:
            await message.answer("❌ Нет настроенных чатов")
            return

        # Определяем действие на основе первого чата
        first_chat = chat_groups[0]
        new_status = not first_chat.is_active
        action_text = "включить" if new_status else "отключить"

        text = ADMIN_CHAT_TOGGLE_CONFIRM.format(
            action_text=action_text, chat_count=len(chat_groups)
        )

        builder = InlineKeyboardBuilder()
        builder.button(text=f"✅ {action_text.title()}", callback_data=f"admin_chat_toggle_all_{new_status}")
        builder.button(text="❌ Отмена", callback_data="admin_panel")
        builder.adjust(1)

        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")

    except Exception as e:
        logger.error(f"(A) {db_user.tg_user_id} - команда /chat_toggle_all: {e}")
        await message.answer("Произошла ошибка при управлении чатами")


@router.callback_query(F.data.startswith("admin_chat_toggle_all_"))
async def callback_chat_toggle_all(callback: CallbackQuery, db_user):
    """Обработчик массового переключения активности чатов"""
    if not is_admin(db_user.tg_user_id):
        await callback.answer("❌ Нет прав доступа", show_alert=True)
        return

    await callback.answer("Выполняю операцию...")

    try:
        from src.bot.services.chat_service import chat_service

        # Парсим статус
        new_status = callback.data.split("_")[-1] == "True"

        # Получаем все чаты
        chat_groups = await chat_service.get_all_chat_groups()

        updated_count = 0
        async with db_manager.async_session() as session:
            for chat_group in chat_groups:
                chat_group.is_active = new_status
                session.add(chat_group)
                updated_count += 1

            await session.commit()

        action_text = "включены" if new_status else "отключены"
        result_text = "✅ <b>Операция завершена</b>\n\n"
        result_text += f"Уведомления {action_text} в {updated_count} чатах."

        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 Назад", callback_data="admin_chat_management")

        await safe_edit_message(callback.message, result_text, reply_markup=builder.as_markup(), parse_mode="HTML")

    except Exception as e:
        user_id = callback.from_user.id if callback.from_user else 0
        logger.error(f"(A) {user_id} - переключение всех чатов: {e}")
        await safe_edit_message(callback.message, ERROR_CHAT_TOGGLE)


def register_admin_handlers(dp):
    """Регистрация admin handlers"""
    dp.include_router(router)
