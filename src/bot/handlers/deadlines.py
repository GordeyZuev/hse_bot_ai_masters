import re
from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.filters import Command, and_f
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.bot.services.deadline_service import deadline_service
from src.bot.services.task_status_service import task_status_service
from src.bot.texts import DEADLINES_ALL_DONE, DEADLINES_ERROR, DEADLINES_TITLE, DEADLINES_TOTAL
from src.utils import get_logger, safe_edit_message
from src.utils.notification_formatting import (
    format_deadline_datetime,
    format_time_remaining,
)


logger = get_logger()
router = Router()

FEATURE_ENABLE_TASK_COMPLETION = False


def _format_deadlines_with_divider(
    all_deadlines: list[dict], days: int, user_tz_name: str, hide_done: bool = True, deadline_numbers: dict[int, int] | None = None
) -> str:
    """Форматирование списка дедлайнов с разделителем между выполненными и невыполненными"""
    if not all_deadlines:
        return deadline_service.format_deadlines_list([], days, user_tz_name=user_tz_name)

    if deadline_numbers is None:
        all_sorted = sorted(
            all_deadlines,
            key=lambda x: (
                x.get("nearest_deadline") or datetime.max.replace(tzinfo=UTC),
                x["deadline"].id,
            )
        )
        deadline_numbers = {x["deadline"].id: idx + 1 for idx, x in enumerate(all_sorted)}

    not_done_deadlines = [d for d in all_deadlines if not d.get("is_done", False)]
    done_deadlines = [d for d in all_deadlines if d.get("is_done", False)]

    not_done_deadlines.sort(
        key=lambda x: (
            x.get("nearest_deadline") or datetime.max.replace(tzinfo=UTC),
            x["deadline"].id,
        )
    )
    done_deadlines.sort(
        key=lambda x: (
            x.get("nearest_deadline") or datetime.max.replace(tzinfo=UTC),
            x["deadline"].id,
        )
    )

    if not not_done_deadlines and done_deadlines and hide_done:
        return DEADLINES_ALL_DONE.format(days=days)

    text = DEADLINES_TITLE.format(days=days)

    if not_done_deadlines:
        for data in not_done_deadlines:
            deadline = data["deadline"]
            subject = data["subject"]
            i = deadline_numbers[deadline.id]

            text += f"<b>{i}. {subject.name}</b>\n"
            if deadline.source_link:
                text += f"📝 <a href='{deadline.source_link}'>{deadline.hw_name}</a>\n"
            else:
                text += f"📝 {deadline.hw_name}\n"

            if data.get("nearest_deadline"):
                now = datetime.now(UTC)
                date_str = format_deadline_datetime(data["nearest_deadline"], user_tz_name)
                deadline_type_icon = "🟡" if data["deadline_type"] == "soft" else "🔴"
                remain = format_time_remaining(data["nearest_deadline"], now)
                text += f"{deadline_type_icon} {date_str} {remain}"

            text += "\n\n"

    if not_done_deadlines and done_deadlines and not hide_done:
        text += "\n"

    if done_deadlines and not hide_done:
        for data in done_deadlines:
            deadline = data["deadline"]
            subject = data["subject"]
            i = deadline_numbers[deadline.id]

            text += f"<b>{i}. {subject.name}</b>\n"
            if deadline.source_link:
                text += f"📝 <a href='{deadline.source_link}'>{deadline.hw_name}</a>\n"
            else:
                text += f"📝 {deadline.hw_name}\n"

            if data.get("nearest_deadline"):
                now = datetime.now(UTC)
                date_str = format_deadline_datetime(data["nearest_deadline"], user_tz_name)
                remain = format_time_remaining(data["nearest_deadline"], now)
                text += f"✅ {date_str} {remain}"

            text += "\n\n"

    text += DEADLINES_TOTAL.format(count=len(all_deadlines))
    return text


@router.message(and_f(Command("deadlines"), F.chat.type == "private"))
async def cmd_deadlines(message: Message, db_user):
    """Обработчик команды /deadlines [N]"""
    try:
        days = 7

        text = message.text.strip()
        match = re.search(r"/deadlines\s+(\d+)", text)
        if match:
            try:
                days = int(match.group(1))
                if days < 1:
                    days = 1
                elif days > 365:
                    days = 365
            except ValueError:
                days = 7

        await send_deadlines_list(message, db_user, days, hide_done=True)

    except Exception as e:
        user_id = message.from_user.id if message.from_user else 0
        logger.error(f"(U) {user_id} - команда /deadlines: {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")


@router.callback_query(F.data == "quick_deadlines")
async def callback_deadlines(callback: CallbackQuery, db_user):
    """Обработчик кнопки быстрого доступа к дедлайнам"""
    await callback.answer()
    await send_deadlines_list(callback.message, db_user, 7, hide_done=True, edit=True)


@router.callback_query(F.data.startswith("deadlines_"))
async def callback_deadlines_period(callback: CallbackQuery, db_user):
    """Обработчик выбора периода дедлайнов"""
    await callback.answer()

    try:
        parts = callback.data.split("_")
        days = int(parts[1])
        hide_done = True
        if len(parts) >= 3 and parts[2].startswith("h"):
            hide_done = parts[2] == "h1"
        await send_deadlines_list(callback.message, db_user, days, hide_done=hide_done, edit=True)
    except (ValueError, IndexError):
        await callback.answer("Ошибка выбора периода", show_alert=True)


async def send_deadlines_list(message: Message, db_user, days: int, hide_done: bool = True, edit: bool = False):
    """Отправка списка дедлайнов"""
    try:
        # Всегда получаем все дедлайны (для правильного форматирования с разделителем)
        all_deadlines = await deadline_service.get_user_deadlines(
            db_user.tg_user_id, days, hide_done=False
        )

        # Форматируем сообщение с разделителем
        text = _format_deadlines_with_divider(all_deadlines, days, db_user.timezone, hide_done)

        # Создаем клавиатуру с стандартными кнопками
        builder = InlineKeyboardBuilder()

        periods = [(7, "7 дней"), (15, "15 дней"), (30, "30 дней")]
        for period_days, period_text in periods:
            if period_days == days:
                button_text = f"🔷 {period_text}"
                callback_data = f"current_{period_days}_h{1 if hide_done else 0}"
            else:
                button_text = period_text
                callback_data = f"deadlines_{period_days}_h{1 if hide_done else 0}"
            builder.button(text=button_text, callback_data=callback_data)

        if not all_deadlines:
            builder.button(text="📚 Подписки", callback_data="quick_sub")
            builder.button(text="🔙 Назад", callback_data="back_to_menu")
            builder.adjust(3, 1, 1)
        else:
            if FEATURE_ENABLE_TASK_COMPLETION:
                builder.button(
                    text=(
                        "🙈 Скрыть выполненные" if not hide_done else "🐵 Показать выполненные"
                    ),
                    callback_data=f"toggle_hide_done_{days}_h{1 if hide_done else 0}",
                )
                builder.button(
                    text="📝 Отметить выполненные",
                    callback_data=f"mark_done_all_{days}_h{1 if hide_done else 0}",
                )
            builder.button(text="🔙 Назад", callback_data="back_to_menu")
            if FEATURE_ENABLE_TASK_COMPLETION:
                builder.adjust(3, 1, 1, 1)
            else:
                builder.adjust(3, 1)

        if edit:
            await message.edit_text(
                text, reply_markup=builder.as_markup(), disable_web_page_preview=True
            )
        else:
            await message.answer(
                text, reply_markup=builder.as_markup(), disable_web_page_preview=True
            )

        logger.info(
            f"(U) {db_user.tg_user_id} - Дедлайны на {days} дней"
        )

    except Exception as e:
        if "message is not modified" in str(e):
            logger.warning(f"Сообщение не изменилось (пользователь нажал на тот же период): {e}")
            return
        else:
            logger.error(f"Ошибка отправки списка дедлайнов: {e}")
            error_text = DEADLINES_ERROR

            if edit:
                await safe_edit_message(message, error_text)
            else:
                await message.answer(error_text)


async def send_deadlines_list_for_checking(message: Message, db_user, days: int, hide_done: bool = False, edit: bool = False):
    """Отправка списка дедлайнов в режиме отметки выполненных"""
    try:
        # Получаем все дедлайны пользователя (всегда показываем все в режиме отметки)
        deadlines_data = await deadline_service.get_user_deadlines(
            db_user.tg_user_id, days, hide_done=False
        )
        all_deadlines = deadlines_data

        # Создаем стабильную нумерацию на основе сортировки всех дедлайнов (независимо от статуса)
        # Сортируем все дедлайны по ближайшему дедлайну и ID для стабильности
        all_sorted = sorted(
            deadlines_data,
            key=lambda x: (
                x.get("nearest_deadline") or datetime.max.replace(tzinfo=UTC),
                x["deadline"].id,
            )
        )
        # Создаем стабильную нумерацию на основе отсортированного списка
        deadline_numbers = {x["deadline"].id: idx + 1 for idx, x in enumerate(all_sorted)}

        # В режиме отметки всегда показываем все задания (и выполненные, и невыполненные)
        # Разделяем на выполненные и невыполненные для форматирования текста
        not_done_deadlines = [d for d in deadlines_data if not d.get("is_done", False)]
        done_deadlines = [d for d in deadlines_data if d.get("is_done", False)]

        # Сортируем каждую группу по ближайшему дедлайну (для стабильности при одинаковых датах используем ID)
        not_done_deadlines.sort(
            key=lambda x: (
                x.get("nearest_deadline") or datetime.max.replace(tzinfo=UTC),
                x["deadline"].id,
            )
        )
        done_deadlines.sort(
            key=lambda x: (
                x.get("nearest_deadline") or datetime.max.replace(tzinfo=UTC),
                x["deadline"].id,
            )
        )

        # Переупорядочиваем deadlines_data для форматирования текста: сначала невыполненные, потом выполненные
        deadlines_data_for_text = not_done_deadlines + done_deadlines

        # Для кнопок используем стабильный порядок (all_sorted), чтобы кнопки не перемещались
        sorted_all = all_sorted

        # Форматируем текст с разделителем (всегда показываем выполненные)
        # Передаем стабильную нумерацию, чтобы номера в тексте совпадали с номерами на кнопках
        text = _format_deadlines_with_divider(deadlines_data_for_text, days, db_user.timezone, hide_done=False, deadline_numbers=deadline_numbers)

        # Периоды (3 кнопки в один ряд)
        periods_builder = InlineKeyboardBuilder()
        periods = [(7, "7 дней"), (15, "15 дней"), (30, "30 дней")]
        for period_days, period_text in periods:
            if period_days == days:
                button_text = f"🔷 {period_text}"
                callback_data = f"check_current_{period_days}_h{1 if hide_done else 0}"
            else:
                button_text = period_text
                callback_data = f"check_period_{period_days}_h{1 if hide_done else 0}"
            periods_builder.button(text=button_text, callback_data=callback_data)
        periods_builder.adjust(3)

        # Дедлайны (по 4 кнопки в ряд)
        # Используем исходный отсортированный список для кнопок, чтобы они не перемещались
        deadlines_builder = InlineKeyboardBuilder()
        if FEATURE_ENABLE_TASK_COMPLETION and all_deadlines:
            for d in sorted_all:
                deadline = d["deadline"]
                is_done = d.get("is_done", False)
                icon = "✅" if is_done else "☑️"
                idx = deadline_numbers[deadline.id]
                button_text = f"{idx}. {icon}"
                callback_data = f"quick_toggle_{deadline.id}_{days}_h{1 if hide_done else 0}"
                deadlines_builder.button(text=button_text, callback_data=callback_data)
            deadlines_builder.adjust(4)

        # Кнопки снизу
        bottom_builder = InlineKeyboardBuilder()
        if not all_deadlines:
            bottom_builder.button(text="📚 Подписки", callback_data="quick_sub")
            bottom_builder.button(text="🔙 Назад", callback_data="back_to_menu")
            bottom_builder.adjust(2)
        else:
            bottom_builder.button(text="🔙 Сохранить и выйти", callback_data=f"deadlines_{days}_h{1 if hide_done else 0}")
            bottom_builder.adjust(1)

        # Объединяем все построители
        builder = InlineKeyboardBuilder()
        builder.attach(periods_builder)
        if FEATURE_ENABLE_TASK_COMPLETION and all_deadlines and deadlines_builder.buttons:
            builder.attach(deadlines_builder)
        builder.attach(bottom_builder)

        if edit:
            await message.edit_text(
                text, reply_markup=builder.as_markup(), disable_web_page_preview=True
            )
        else:
            await message.answer(
                text, reply_markup=builder.as_markup(), disable_web_page_preview=True
            )

        logger.info(
            f"(U) {db_user.tg_user_id} - Режим отметки выполненных на {days} дней"
        )

    except Exception as e:
        if "message is not modified" in str(e):
            logger.warning(f"Сообщение не изменилось: {e}")
            return
        else:
            logger.error(f"Ошибка отправки списка дедлайнов в режиме отметки: {e}")
            error_text = DEADLINES_ERROR

            if edit:
                await safe_edit_message(message, error_text)
            else:
                await message.answer(error_text)


@router.callback_query(F.data.startswith("current_"))
async def callback_current_period(callback: CallbackQuery):
    """Обработчик нажатия на текущий период"""
    await callback.answer("Уже выбран этот период", show_alert=False)


@router.callback_query(F.data.startswith("toggle_hide_done_"))
async def callback_toggle_hide_done(callback: CallbackQuery, db_user):
    await callback.answer()
    parts = callback.data.split("_")
    try:
        days = int(parts[3])
        hide_done = parts[4] == "h1"
        await send_deadlines_list(
            callback.message, db_user, days, hide_done=not hide_done, edit=True
        )
    except Exception:
        await callback.answer("Ошибка переключения фильтра", show_alert=True)


@router.callback_query(F.data.startswith("check_current_"))
async def callback_check_current_period(callback: CallbackQuery):
    """Обработчик нажатия на текущий период в режиме отметки"""
    await callback.answer("Уже выбран этот период", show_alert=False)


@router.callback_query(F.data.startswith("check_period_"))
async def callback_check_period(callback: CallbackQuery, db_user):
    """Обработчик выбора периода в режиме отметки"""
    await callback.answer()
    parts = callback.data.split("_")
    try:
        days = int(parts[2])
        hide_done = parts[3] == "h1"
        await send_deadlines_list_for_checking(callback.message, db_user, days, hide_done=hide_done, edit=True)
    except (ValueError, IndexError):
        await callback.answer("Ошибка выбора периода", show_alert=True)


@router.callback_query(F.data.startswith("mark_done_all_"))
async def callback_mark_done_all(callback: CallbackQuery, db_user):
    """Показать все дедлайны с кнопками галочек в 4 колонки в режиме отметки"""
    await callback.answer()
    parts = callback.data.split("_")
    days = int(parts[3])
    hide_done = parts[4] == "h1"

    await send_deadlines_list_for_checking(callback.message, db_user, days, hide_done=hide_done, edit=True)


@router.callback_query(F.data.startswith("mark_done_subjects_"))
async def callback_mark_done_subjects(callback: CallbackQuery, db_user):
    await callback.answer()
    parts = callback.data.split("_")
    days = int(parts[3])
    hide_done = parts[4] == "h1"

    deadlines_data = await deadline_service.get_user_deadlines(
        db_user.tg_user_id, days, hide_done=False  # в режиме отметки показываем все
    )

    # Список предметов
    subjects = {}
    for d in deadlines_data:
        subj = d["subject"]
        subjects.setdefault(subj.id, {"subject": subj, "count": 0})
        subjects[subj.id]["count"] += 1

    builder = InlineKeyboardBuilder()
    for sid, item in subjects.items():
        subj = item["subject"]
        cnt = item["count"]
        builder.button(
            text=f"{subj.name} ({cnt})"[:64],
            callback_data=f"mark_done_subject_{sid}_{days}_h{1 if hide_done else 0}",
        )

    builder.row()
    builder.button(text="⬅️ Назад к списку", callback_data=f"deadlines_{days}_h{1 if hide_done else 0}")
    builder.adjust(1, 1)

    await safe_edit_message(
        callback.message, "Выберите предмет:", reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("mark_done_subject_"))
async def callback_mark_done_subject(callback: CallbackQuery, db_user):
    await callback.answer()
    parts = callback.data.split("_")
    subject_id = int(parts[3])
    days = int(parts[4])
    hide_done = parts[5] == "h1"

    # Показываем задания по предмету
    deadlines_data = await deadline_service.get_user_deadlines(
        db_user.tg_user_id, days, hide_done=False
    )
    filtered = [d for d in deadlines_data if d["subject"].id == subject_id]
    subject_name = next((d["subject"].name for d in filtered), "Предмет")

    builder = InlineKeyboardBuilder()
    for d in filtered:
        deadline = d["deadline"]
        is_done = d.get("is_done", False)
        icon = "✅" if is_done else "☑️"
        text = f"{icon} {deadline.hw_name}"
        cb = f"toggle_task_{deadline.id}_{subject_id}_{days}_h{1 if hide_done else 0}"
        builder.button(text=text[:64], callback_data=cb)

    # Навигация: две кнопки в одном ряду
    builder.button(text="⬅️ К предметам", callback_data=f"mark_done_subjects_{days}_h{1 if hide_done else 0}")
    builder.button(text="📋 К списку", callback_data=f"deadlines_{days}_h{1 if hide_done else 0}")

    # Раскладка: каждое ДЗ на своем ряду (1), навигация на одном ряду (2)
    num_tasks = len(filtered)
    adjust_params = [1] * num_tasks + [2]
    builder.adjust(*adjust_params)

    await safe_edit_message(
        callback.message, f"<b>{subject_name}</b>\n\nОтметьте выполненные задания:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.callback_query(F.data.startswith("toggle_task_"))
async def callback_toggle_task(callback: CallbackQuery, db_user):
    await callback.answer()
    parts = callback.data.split("_")
    deadline_id = int(parts[2])
    int(parts[3])
    days = int(parts[4])

    data = await deadline_service.get_user_deadlines(db_user.tg_user_id, days, hide_done=False)
    current = next((x for x in data if x["deadline"].id == deadline_id), None)
    if current and current.get("is_done"):
        await task_status_service.set_not_done(db_user.tg_user_id, deadline_id)
    else:
        await task_status_service.set_done(db_user.tg_user_id, deadline_id)
        if current:
            deadline = current["deadline"]
            subject = current["subject"]
            logger.info(
                f"(U) {db_user.tg_user_id} - Отметил ДЗ выполненным: {subject.name} - {deadline.hw_name} (deadline_id={deadline_id})"
            )

    # Перерисовать экран предмета
    await callback_mark_done_subject(callback, db_user)


@router.callback_query(F.data.startswith("quick_toggle_"))
async def callback_quick_toggle(callback: CallbackQuery, db_user):
    """Быстрое переключение статуса дедлайна прямо из списка"""
    await callback.answer()
    parts = callback.data.split("_")
    deadline_id = int(parts[2])
    days = int(parts[3])
    hide_done = parts[4] == "h1"

    data = await deadline_service.get_user_deadlines(db_user.tg_user_id, days, hide_done=False)
    current = next((x for x in data if x["deadline"].id == deadline_id), None)
    if current and current.get("is_done"):
        await task_status_service.set_not_done(db_user.tg_user_id, deadline_id)
    else:
        await task_status_service.set_done(db_user.tg_user_id, deadline_id)
        if current:
            deadline = current["deadline"]
            subject = current["subject"]
            logger.info(
                f"(U) {db_user.tg_user_id} - Отметил ДЗ выполненным: {subject.name} - {deadline.hw_name} (deadline_id={deadline_id})"
            )

    # quick_toggle вызывается только из режима отметки, всегда возвращаемся туда
    await send_deadlines_list_for_checking(callback.message, db_user, days, hide_done=hide_done, edit=True)


@router.callback_query(F.data == "divider_ignore")
async def callback_divider_ignore(callback: CallbackQuery):
    """Обработчик нажатия на разделитель (ничего не делает)"""
    await callback.answer()


def register_deadline_handlers(dp):
    """Регистрация handlers для дедлайнов"""
    dp.include_router(router)
