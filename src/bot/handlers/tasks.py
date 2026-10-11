import os
import re
from datetime import UTC, datetime
from html import escape
from math import ceil

from aiogram import F, Router
from aiogram.enums import ButtonStyle
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, and_f
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.bot.presentation import (
    build_rich_deadlines,
    build_rich_deadlines_keyboard,
    rich_page_count,
)
from src.bot.services.deadline_service import deadline_service
from src.bot.services.notification_service import notification_service
from src.bot.services.task_status_service import task_status_service
from src.bot.services.user_action_events import record_user_action_event
from src.bot.texts import (
    DEADLINES_ERROR,
    DEADLINES_TOTAL,
)
from src.utils import get_logger, safe_edit_message
from src.utils.notification_formatting import (
    format_deadline_tg_time,
    format_time_remaining,
)


logger = get_logger()
router = Router()

ALL_DEADLINES_THRESHOLD = 100
COMPACT_MAX_TEXT_LENGTH = 3500  # Leave room for page labels and Telegram entities.


def _preview_name(value: str, limit: int) -> str:
    return value if len(value) <= limit else f"{value[: limit - 1]}…"


async def _edit_or_send(message: Message, text: str, **kwargs) -> None:
    """Keep callback navigation in one message unless that message is gone."""
    try:
        await message.edit_text(text, **kwargs)
    except TelegramBadRequest as exc:
        error = str(exc).lower()
        if "message is not modified" in error:
            return
        if "message to edit not found" in error or "message not found" in error:
            await message.answer(text, **kwargs)
            return
        raise


def _deadlines_title(days: int) -> str:
    """Заголовок списка дедлайнов: 'Все дедлайны' или 'Дедлайны на N дней'"""
    if days >= ALL_DEADLINES_THRESHOLD:
        return "📅 <b>Все дедлайны</b>"
    return f"📅 <b>Дедлайны на {days} дней</b>"


async def _set_task_status(
    user_id: int, task_id: int, target: str, *, surface: str
) -> bool:
    """Apply the action shown on a button, never invert a possibly stale state."""
    if target == "done":
        return await task_status_service.set_done(user_id, task_id, surface=surface)
    if target == "work":
        return await task_status_service.set_not_done(user_id, task_id, surface=surface)
    raise ValueError("Unknown task status target")


def _task_status_answer(target: str, changed: bool) -> str:
    if target == "done":
        return "✅ Задание отмечено выполненным" if changed else "Задание уже выполнено"
    return "↩️ Задание возвращено в работу" if changed else "Задание уже в работе"


def _format_single_deadline(
    data: dict,
    deadline_numbers: dict[int, int],
    user_tz_name: str,
    is_done: bool = False,
) -> str:
    """Форматирование одного дедлайна"""
    deadline = data["deadline"]
    subject = data["subject"]
    i = deadline_numbers[deadline.id]

    subject_name = _preview_name(subject.name, 120)
    task_name = _preview_name(deadline.hw_name or "Без названия", 160)
    text = f"<b>{i}. {escape(subject_name)}</b>\n"
    # An unusually long URL can make even a one-item message unsendable.
    if deadline.source_link and len(deadline.source_link) <= 1024:
        text += (
            f"• 📝 <a href='{escape(deadline.source_link, quote=True)}'>"
            f"{escape(task_name)}</a>\n"
        )
    else:
        text += f"• 📝 {escape(task_name)}\n"

    if data.get("nearest_deadline"):
        now = datetime.now(UTC)
        date_str = format_deadline_tg_time(
            data["nearest_deadline"], tz_name=user_tz_name
        )

        if is_done:
            remain = format_time_remaining(data["nearest_deadline"], now)
            text += f"• ✅ {date_str} {remain}"
        else:
            deadline_type_icon = "🟡" if data["deadline_type"] == "soft" else "🔴"
            remain = format_time_remaining(data["nearest_deadline"], now)
            text += f"• {deadline_type_icon} {date_str} {remain}"

    return text


def _compact_deadline_pages(
    all_deadlines: list[dict], days: int, user_tz_name: str, hide_done: bool
) -> list[str]:
    """Fit complete task rows into Telegram text messages with stable numbering."""
    ordered = sorted(
        all_deadlines,
        key=lambda item: (
            item.get("nearest_deadline") or datetime.max.replace(tzinfo=UTC),
            item["deadline"].id,
        ),
    )
    numbers = {item["deadline"].id: i for i, item in enumerate(ordered, 1)}
    visible = [
        item for item in ordered if not (hide_done and item.get("is_done", False))
    ]
    visible.sort(key=lambda item: bool(item.get("is_done", False)))
    if not visible:
        return [
            _format_deadlines_with_divider(all_deadlines, days, user_tz_name, hide_done)
        ]

    def render(items: list[dict]) -> str:
        return _format_deadlines_with_divider(
            items,
            days,
            user_tz_name,
            hide_done,
            deadline_numbers=numbers,
            total_count=len(all_deadlines),
        )

    chunks: list[list[dict]] = []
    current: list[dict] = []
    for item in visible:
        candidate = [*current, item]
        if current and len(render(candidate)) > COMPACT_MAX_TEXT_LENGTH:
            chunks.append(current)
            current = [item]
        else:
            current = candidate
    chunks.append(current)
    pages = [render(chunk) for chunk in chunks]
    if len(pages) > 1:
        pages = [
            f"{text}\nСтраница {i}/{len(pages)}" for i, text in enumerate(pages, 1)
        ]
    return pages


def _format_deadlines_with_divider(
    all_deadlines: list[dict],
    days: int,
    user_tz_name: str,
    hide_done: bool = True,
    deadline_numbers: dict[int, int] | None = None,
    total_count: int | None = None,
) -> str:
    """Форматирование списка дедлайнов с разделителем между выполненными и невыполненными"""
    if not all_deadlines:
        return deadline_service.format_deadlines_list(
            [], days, user_tz_name=user_tz_name
        )

    if deadline_numbers is None:
        all_sorted = sorted(
            all_deadlines,
            key=lambda x: (
                x.get("nearest_deadline") or datetime.max.replace(tzinfo=UTC),
                x["deadline"].id,
            ),
        )
        deadline_numbers = {
            x["deadline"].id: idx + 1 for idx, x in enumerate(all_sorted)
        }

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
        return _deadlines_title(days) + "\n\nВы все выполнили! Поздравляем!"

    text = _deadlines_title(days) + "\n\n"

    if not_done_deadlines:
        for idx, data in enumerate(not_done_deadlines):
            if idx > 0:
                text += "\n"
            text += _format_single_deadline(
                data, deadline_numbers, user_tz_name, is_done=False
            )
            text += "\n\n"

    if not_done_deadlines and done_deadlines and not hide_done:
        text += "\n"

    if done_deadlines and not hide_done:
        for data in done_deadlines:
            text += _format_single_deadline(
                data, deadline_numbers, user_tz_name, is_done=True
            )
            text += "\n\n"

    text += DEADLINES_TOTAL.format(
        count=len(all_deadlines) if total_count is None else total_count
    )
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
                elif days > 500:
                    days = 500
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


@router.callback_query(F.data.regexp(r"^deadlines_\d+_h[01]$"))
async def callback_deadlines_period(callback: CallbackQuery, db_user):
    """Обработчик выбора периода дедлайнов"""
    try:
        parts = callback.data.split("_")
        days = int(parts[1])
        hide_done = True
        if len(parts) >= 3 and parts[2].startswith("h"):
            hide_done = parts[2] == "h1"
    except (ValueError, IndexError):
        await callback.answer("Ошибка выбора периода", show_alert=True)
        return
    await callback.answer()
    await send_deadlines_list(
        callback.message, db_user, days, hide_done=hide_done, edit=True
    )


async def send_deadlines_list(
    message: Message,
    db_user,
    days: int,
    hide_done: bool = True,
    edit: bool = False,
    page: int = 0,
    open_task_id: int | None = None,
):
    """Отправка списка дедлайнов"""
    try:
        # Всегда получаем все дедлайны (для правильного форматирования с разделителем)
        all_deadlines = await deadline_service.get_user_deadlines(
            db_user.tg_user_id, days, hide_done=False
        )

        user_tz = db_user.timezone or "Europe/Moscow"
        filtered_deadlines = [
            item
            for item in all_deadlines
            if not (hide_done and item.get("is_done", False))
        ]
        filtered_deadlines.sort(
            key=lambda item: (
                item.get("nearest_deadline") or datetime.max.replace(tzinfo=UTC),
                item["deadline"].id,
            )
        )
        rich_enabled = os.getenv("RICH_MESSAGES_ENABLED", "false").lower() in {
            "1",
            "true",
            "yes",
        }
        use_rich = False
        if rich_enabled:
            try:
                settings = await notification_service.get_user_notification_settings(
                    db_user.tg_user_id
                )
                use_rich = settings.display_mode == "rich"
            except Exception:
                logger.exception(
                    "Не удалось прочитать настройку Rich; показан обычный список"
                )
        if use_rich:
            try:
                rich_pages = rich_page_count(filtered_deadlines)
                rich_page = min(max(page, 0), rich_pages - 1)
                rich_message = build_rich_deadlines(
                    filtered_deadlines,
                    days,
                    hide_done,
                    rich_page,
                    user_tz,
                    open_task_id=open_task_id,
                )
                rich_markup = build_rich_deadlines_keyboard(
                    filtered_deadlines, days, hide_done, rich_page
                )
                if edit:
                    try:
                        await message.edit_text(
                            text=None,
                            rich_message=rich_message,
                            reply_markup=rich_markup,
                        )
                    except TelegramBadRequest as exc:
                        if "message is not modified" not in str(exc).lower():
                            raise
                else:
                    await message.bot.send_rich_message(
                        chat_id=message.chat.id,
                        rich_message=rich_message,
                        reply_markup=rich_markup,
                    )
                logger.info(f"(U) {db_user.tg_user_id} - Rich дедлайны на {days} дней")
                await record_user_action_event(
                    user_id=db_user.tg_user_id,
                    event_name="deadlines_opened",
                    surface="rich",
                    details={"days": days, "hide_done": hide_done, "page": rich_page},
                )
                return
            except Exception as rich_error:
                logger.warning(
                    f"(U) {db_user.tg_user_id} - Rich fallback: {rich_error}"
                )

        # В стандартном режиме сохраняем прежний вид списка и клавиатуры.
        compact_pages = _compact_deadline_pages(all_deadlines, days, user_tz, hide_done)
        compact_page = min(max(page, 0), len(compact_pages) - 1)
        text = compact_pages[compact_page]
        builder = InlineKeyboardBuilder()
        periods = [(7, "7 дней"), (15, "15 дней"), (500, "Все")]
        for period_days, period_text in periods:
            if period_days == days:
                button_text = f"🔷 {period_text}"
                callback_data = f"current_{period_days}_h{1 if hide_done else 0}"
                builder.button(
                    text=button_text,
                    callback_data=callback_data,
                    style=ButtonStyle.PRIMARY,
                )
            else:
                button_text = period_text
                callback_data = f"deadlines_{period_days}_h{1 if hide_done else 0}"
                builder.button(text=button_text, callback_data=callback_data)

        navigation_count = 0
        if len(compact_pages) > 1:
            if compact_page > 0:
                builder.button(
                    text="← Назад",
                    callback_data=f"deadlines_page_{days}_{compact_page - 1}_h{int(hide_done)}",
                )
                navigation_count += 1
            if compact_page + 1 < len(compact_pages):
                builder.button(
                    text="Далее →",
                    callback_data=f"deadlines_page_{days}_{compact_page + 1}_h{int(hide_done)}",
                )
                navigation_count += 1

        if not all_deadlines:
            builder.button(text="📚 Подписки", callback_data="quick_subjects")
            builder.button(text="🔙 Назад", callback_data="back_to_menu")
            builder.adjust(3, *([navigation_count] if navigation_count else []), 1, 1)
        else:
            builder.button(
                text=(
                    "🙈 Скрыть выполненные"
                    if not hide_done
                    else "🐵 Показать выполненные"
                ),
                callback_data=f"toggle_hide_done_{days}_h{1 if hide_done else 0}",
                style=ButtonStyle.PRIMARY if not hide_done else None,
            )
            builder.button(
                text="📝 Отметить выполненные",
                callback_data=f"mark_done_all_{days}_h{1 if hide_done else 0}",
            )
            builder.button(text="🔙 Назад", callback_data="back_to_menu")
            builder.adjust(
                3, *([navigation_count] if navigation_count else []), 1, 1, 1
            )

        if edit:
            await _edit_or_send(
                message,
                text,
                reply_markup=builder.as_markup(),
                disable_web_page_preview=True,
            )
        else:
            await message.answer(
                text, reply_markup=builder.as_markup(), disable_web_page_preview=True
            )

        logger.info(f"(U) {db_user.tg_user_id} - Дедлайны на {days} дней")
        await record_user_action_event(
            user_id=db_user.tg_user_id,
            event_name="deadlines_opened",
            surface="compact",
            details={"days": days, "hide_done": hide_done, "page": compact_page},
        )

    except Exception as e:
        if "message is not modified" in str(e):
            logger.warning(
                f"Сообщение не изменилось (пользователь нажал на тот же период): {e}"
            )
            return
        else:
            logger.error(f"Ошибка отправки списка дедлайнов: {e}")
            error_text = DEADLINES_ERROR

            if edit:
                await safe_edit_message(message, error_text)
            else:
                await message.answer(error_text)


@router.callback_query(F.data.startswith("rich_deadlines_"))
async def callback_rich_deadlines(callback: CallbackQuery, db_user):
    try:
        parts = callback.data.split("_")
        days = int(parts[2])
        page = int(parts[3])
        hide_done = parts[4] == "h1"
    except (ValueError, IndexError):
        await callback.answer("Ошибка страницы", show_alert=True)
        return
    await callback.answer()
    await send_deadlines_list(
        callback.message,
        db_user,
        days,
        hide_done=hide_done,
        edit=True,
        page=page,
    )


@router.callback_query(F.data.regexp(r"^rich_current_\d+$"))
async def callback_rich_current(callback: CallbackQuery):
    await callback.answer("Уже выбран этот период")


@router.callback_query(F.data.startswith("deadlines_page_"))
async def callback_deadlines_page(callback: CallbackQuery, db_user):
    try:
        parts = callback.data.split("_")
        days = int(parts[2])
        page = int(parts[3])
        hide_done = parts[4] == "h1"
    except (ValueError, IndexError):
        await callback.answer("Ошибка страницы", show_alert=True)
        return
    await callback.answer()
    await send_deadlines_list(
        callback.message,
        db_user,
        days,
        hide_done=hide_done,
        edit=True,
        page=page,
    )


async def _task_card_payload(
    db_user, task_id: int, days: int, page: int, hide_done: bool
):
    # Совместимость с уже отправленными сообщениями прежнего варианта интерфейса.
    data = await deadline_service.get_user_deadlines(
        db_user.tg_user_id, days, hide_done=False
    )
    item = next((entry for entry in data if entry["deadline"].id == task_id), None)
    if item is None:
        return None

    task = item["deadline"]
    subject = item["subject"]
    tz_name = db_user.timezone or "Europe/Moscow"
    lines = [
        f"📚 <b>{escape(subject.name[:150])}</b>",
        f"📝 <b>{escape((task.hw_name or 'Без названия')[:500])}</b>",
        "",
    ]
    for label, timestamp in (
        ("🟡 Мягкий дедлайн", task.soft_deadline_ts),
        ("🔴 Жёсткий дедлайн", task.hard_deadline_ts),
    ):
        if timestamp is not None:
            lines.append(
                f"{label}: {format_deadline_tg_time(timestamp, tz_name=tz_name)}"
            )
    lines.append("\n✅ Выполнено" if item.get("is_done") else "\n☑️ Не выполнено")
    if task.note:
        lines.append(f"\n💬 {escape(task.note[:900])}")

    builder = InlineKeyboardBuilder()
    if task.source_link:
        builder.button(text="🔗 Открыть задание", url=task.source_link)
    builder.button(
        text="↩️ Вернуть в работу" if item.get("is_done") else "✅ Отметить выполненным",
        callback_data=(
            f"task_card_set_{task_id}_{'work' if item.get('is_done') else 'done'}_"
            f"{days}_{page}_h{int(hide_done)}"
        ),
        style=ButtonStyle.DANGER if item.get("is_done") else ButtonStyle.SUCCESS,
    )
    builder.button(
        text="← К списку",
        callback_data=f"deadlines_page_{days}_{page}_h{int(hide_done)}",
    )
    builder.adjust(1)
    return "\n".join(lines), builder.as_markup(), bool(item.get("is_done"))


@router.callback_query(F.data.regexp(r"^task_card_\d+_\d+_\d+_h[01]$"))
async def callback_task_card(callback: CallbackQuery, db_user):
    _, _, task_id, days, page, hide = callback.data.split("_")
    try:
        payload = await _task_card_payload(
            db_user, int(task_id), int(days), int(page), hide == "h1"
        )
    except Exception:
        logger.exception("Не удалось открыть карточку задания")
        await callback.answer("Не удалось загрузить задание", show_alert=True)
        return
    if payload is None:
        await callback.answer("Задание больше не доступно", show_alert=True)
        return
    await callback.answer()
    text, markup, _is_done = payload
    await safe_edit_message(
        callback.message,
        text,
        reply_markup=markup,
        disable_web_page_preview=True,
    )


@router.callback_query(F.data.regexp(r"^task_card_set_\d+_(done|work)_\d+_\d+_h[01]$"))
async def callback_task_card_set(callback: CallbackQuery, db_user):
    _, _, _, task_id, target, days, page, hide = callback.data.split("_")
    task_id, days, page = int(task_id), int(days), int(page)
    hide_done = hide == "h1"
    try:
        payload = await _task_card_payload(db_user, task_id, days, page, hide_done)
    except Exception:
        logger.exception("Не удалось загрузить карточку задания")
        await callback.answer("Не удалось загрузить задание", show_alert=True)
        return
    if payload is None:
        await callback.answer("Задание больше не доступно", show_alert=True)
        return
    try:
        changed = await _set_task_status(
            db_user.tg_user_id, task_id, target, surface="compact_card"
        )
    except Exception:
        logger.exception("Не удалось изменить отметку задания")
        await callback.answer("Не удалось изменить отметку", show_alert=True)
        return
    await callback.answer(_task_status_answer(target, changed))
    updated = await _task_card_payload(db_user, task_id, days, page, hide_done)
    if updated is not None:
        text, markup, _is_done = updated
        await safe_edit_message(
            callback.message,
            text,
            reply_markup=markup,
            disable_web_page_preview=True,
        )


@router.callback_query(F.data.startswith("task_card_toggle_"))
async def callback_old_task_card_toggle(callback: CallbackQuery):
    await callback.answer("Кнопка устарела. Откройте дедлайны заново.", show_alert=True)


async def send_deadlines_list_for_checking(
    message: Message,
    db_user,
    days: int,
    hide_done: bool = False,
    edit: bool = False,
    page: int = 0,
):
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
            ),
        )
        # Создаем стабильную нумерацию на основе отсортированного списка
        deadline_numbers = {
            x["deadline"].id: idx + 1 for idx, x in enumerate(all_sorted)
        }
        page_size = 10
        pages = max(1, ceil(len(all_sorted) / page_size))
        page = max(0, min(page, pages - 1))
        page_data = all_sorted[page * page_size : (page + 1) * page_size]

        # В режиме отметки всегда показываем все задания (и выполненные, и невыполненные)
        # Разделяем на выполненные и невыполненные для форматирования текста
        not_done_deadlines = [d for d in page_data if not d.get("is_done", False)]
        done_deadlines = [d for d in page_data if d.get("is_done", False)]

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
        sorted_all = page_data

        user_tz = db_user.timezone or "Europe/Moscow"
        text = _format_deadlines_with_divider(
            deadlines_data_for_text,
            days,
            user_tz,
            hide_done=False,
            deadline_numbers=deadline_numbers,
            total_count=len(all_deadlines),
        )
        if pages > 1:
            text += f"\nСтраница {page + 1}/{pages}"

        # Периоды (3 кнопки в один ряд)
        periods_builder = InlineKeyboardBuilder()
        periods = [(7, "7 дней"), (15, "15 дней"), (500, "Все")]
        for period_days, period_text in periods:
            if period_days == days:
                button_text = f"🔷 {period_text}"
                callback_data = f"check_current_{period_days}_h{1 if hide_done else 0}"
                periods_builder.button(
                    text=button_text,
                    callback_data=callback_data,
                    style=ButtonStyle.PRIMARY,
                )
            else:
                button_text = period_text
                callback_data = f"check_period_{period_days}_h{1 if hide_done else 0}"
                periods_builder.button(text=button_text, callback_data=callback_data)
        periods_builder.adjust(3)

        # Дедлайны (по 4 кнопки в ряд)
        # Используем исходный отсортированный список для кнопок, чтобы они не перемещались
        deadlines_builder = InlineKeyboardBuilder()
        if all_deadlines:
            for d in sorted_all:
                deadline = d["deadline"]
                is_done = d.get("is_done", False)
                icon = "✅" if is_done else "☑️"
                idx = deadline_numbers[deadline.id]
                button_text = f"{idx}. {icon}"
                target = "work" if is_done else "done"
                callback_data = f"quick_set_{deadline.id}_{target}_{days}_h{1 if hide_done else 0}_p{page}"
                btn_style = ButtonStyle.SUCCESS if is_done else None
                if btn_style:
                    deadlines_builder.button(
                        text=button_text, callback_data=callback_data, style=btn_style
                    )
                else:
                    deadlines_builder.button(
                        text=button_text, callback_data=callback_data
                    )
            deadlines_builder.adjust(4)

        # Кнопки снизу
        bottom_builder = InlineKeyboardBuilder()
        if not all_deadlines:
            bottom_builder.button(text="📚 Подписки", callback_data="quick_subjects")
            bottom_builder.button(text="🔙 Назад", callback_data="back_to_menu")
            bottom_builder.adjust(2)
        else:
            if page > 0:
                bottom_builder.button(
                    text="← Назад",
                    callback_data=f"check_page_{days}_{page - 1}_h{int(hide_done)}",
                )
            if page + 1 < pages:
                bottom_builder.button(
                    text="Далее →",
                    callback_data=f"check_page_{days}_{page + 1}_h{int(hide_done)}",
                )
            bottom_builder.button(
                text="🔙 Сохранить и выйти",
                callback_data=f"deadlines_{days}_h{1 if hide_done else 0}",
                style=ButtonStyle.SUCCESS,
            )
            bottom_builder.adjust(2, 1)

        # Объединяем все построители
        builder = InlineKeyboardBuilder()
        builder.attach(periods_builder)
        if all_deadlines and deadlines_builder.buttons:
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
        await send_deadlines_list_for_checking(
            callback.message, db_user, days, hide_done=hide_done, edit=True
        )
    except (ValueError, IndexError):
        await callback.answer("Ошибка выбора периода", show_alert=True)


@router.callback_query(F.data.startswith("mark_done_all_"))
async def callback_mark_done_all(callback: CallbackQuery, db_user):
    """Показать все дедлайны с кнопками галочек в 4 колонки в режиме отметки"""
    await callback.answer()
    parts = callback.data.split("_")
    days = int(parts[3])
    hide_done = parts[4] == "h1"

    logger.info(f"(U) {db_user.tg_user_id} - Режим отметки выполненных на {days} дней")
    await send_deadlines_list_for_checking(
        callback.message, db_user, days, hide_done=hide_done, edit=True
    )


@router.callback_query(F.data.startswith("check_page_"))
async def callback_check_page(callback: CallbackQuery, db_user):
    try:
        parts = callback.data.split("_")
        days = int(parts[2])
        page = int(parts[3])
        hide_done = parts[4] == "h1"
    except (ValueError, IndexError):
        await callback.answer("Ошибка страницы", show_alert=True)
        return
    await callback.answer()
    await send_deadlines_list_for_checking(
        callback.message, db_user, days, hide_done=hide_done, edit=True, page=page
    )


@router.callback_query(F.data.startswith("mark_done_subjects_"))
async def callback_mark_done_subjects(callback: CallbackQuery, db_user):
    await callback.answer()
    parts = callback.data.split("_")
    days = int(parts[3])
    hide_done = parts[4] == "h1"

    deadlines_data = await deadline_service.get_user_deadlines(
        db_user.tg_user_id,
        days,
        hide_done=False,  # в режиме отметки показываем все
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
    builder.button(
        text="⬅️ Назад к списку",
        callback_data=f"deadlines_{days}_h{1 if hide_done else 0}",
    )
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

    await show_subject_task_checks(callback, db_user, subject_id, days, hide_done)


async def show_subject_task_checks(
    callback: CallbackQuery, db_user, subject_id: int, days: int, hide_done: bool
):

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
        target = "work" if is_done else "done"
        cb = f"subject_task_set_{deadline.id}_{target}_{subject_id}_{days}_h{int(hide_done)}"
        builder.button(text=text[:64], callback_data=cb)

    # Навигация: две кнопки в одном ряду
    builder.button(
        text="⬅️ К предметам",
        callback_data=f"mark_done_subjects_{days}_h{1 if hide_done else 0}",
    )
    builder.button(
        text="📋 К списку", callback_data=f"deadlines_{days}_h{1 if hide_done else 0}"
    )

    # Раскладка: каждое ДЗ на своем ряду (1), навигация на одном ряду (2)
    num_tasks = len(filtered)
    adjust_params = [1] * num_tasks + [2]
    builder.adjust(*adjust_params)

    await safe_edit_message(
        callback.message,
        f"<b>{escape(subject_name)}</b>\n\nОтметьте выполненные задания:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.callback_query(F.data.startswith("subject_task_set_"))
async def callback_subject_task_set(callback: CallbackQuery, db_user):
    parts = callback.data.split("_")
    try:
        deadline_id = int(parts[3])
        target = parts[4]
        if target not in {"done", "work"}:
            raise ValueError("Unknown target")
        subject_id = int(parts[5])
        days = int(parts[6])
        hide_done = parts[7] == "h1"
    except (ValueError, IndexError):
        await callback.answer("Ошибка задания", show_alert=True)
        return

    data = await deadline_service.get_user_deadlines(
        db_user.tg_user_id, days, hide_done=False
    )
    current = next((x for x in data if x["deadline"].id == deadline_id), None)
    if current is None or current["subject"].id != subject_id:
        await callback.answer("Задание больше не доступно", show_alert=True)
        await safe_edit_message(
            callback.message, "Задание больше не доступно в этом списке."
        )
        return
    try:
        changed = await _set_task_status(
            db_user.tg_user_id, deadline_id, target, surface="compact_subject"
        )
    except Exception:
        logger.exception("Не удалось изменить отметку задания")
        await callback.answer("Не удалось изменить отметку", show_alert=True)
        return
    await callback.answer(_task_status_answer(target, changed))

    # Перерисовать экран предмета
    await show_subject_task_checks(callback, db_user, subject_id, days, hide_done)


@router.callback_query(F.data.startswith("toggle_task_"))
async def callback_old_subject_task_toggle(callback: CallbackQuery):
    await callback.answer("Кнопка устарела. Откройте дедлайны заново.", show_alert=True)


@router.callback_query(F.data.startswith("quick_set_"))
async def callback_quick_set(callback: CallbackQuery, db_user):
    """Apply the exact action printed on the button, including after a retry."""
    parts = callback.data.split("_")
    try:
        deadline_id = int(parts[2])
        target = parts[3]
        if target not in {"done", "work"}:
            raise ValueError("Unknown target")
        days = int(parts[4])
        hide_done = parts[5] == "h1"
        page = int(parts[6][1:]) if len(parts) > 6 and parts[6].startswith("p") else 0
    except (ValueError, IndexError):
        await callback.answer("Ошибка задания", show_alert=True)
        return

    data = await deadline_service.get_user_deadlines(
        db_user.tg_user_id, days, hide_done=False
    )
    current = next((x for x in data if x["deadline"].id == deadline_id), None)
    if current is None:
        await callback.answer("Задание больше не доступно", show_alert=True)
        await safe_edit_message(
            callback.message, "Задание больше не доступно в этом списке."
        )
        return
    try:
        changed = await _set_task_status(
            db_user.tg_user_id, deadline_id, target, surface="compact"
        )
    except Exception:
        logger.exception("Не удалось изменить отметку задания")
        await callback.answer("Не удалось изменить отметку", show_alert=True)
        return
    await callback.answer(_task_status_answer(target, changed))

    # quick_toggle вызывается только из режима отметки, всегда возвращаемся туда
    await send_deadlines_list_for_checking(
        callback.message, db_user, days, hide_done=hide_done, edit=True, page=page
    )


@router.callback_query(F.data.startswith("quick_toggle_"))
async def callback_old_quick_toggle(callback: CallbackQuery):
    await callback.answer("Кнопка устарела. Откройте дедлайны заново.", show_alert=True)


@router.callback_query(F.data.startswith("rich_set_"))
async def callback_rich_set(callback: CallbackQuery, db_user):
    """Apply a task action and stay on the same Rich deadline page."""
    parts = callback.data.split("_")
    try:
        deadline_id = int(parts[2])
        target = parts[3]
        if target not in {"done", "work"}:
            raise ValueError("Unknown target")
        days = int(parts[4])
        page = int(parts[5])
        hide_done = parts[6] == "h1"
    except (ValueError, IndexError):
        await callback.answer("Ошибка задания", show_alert=True)
        return

    if not isinstance(callback.message, Message):
        await callback.answer(
            "Сообщение больше недоступно. Откройте дедлайны заново.", show_alert=True
        )
        return
    try:
        data = await deadline_service.get_user_deadlines(
            db_user.tg_user_id, days, hide_done=False
        )
        current = next(
            (item for item in data if item["deadline"].id == deadline_id), None
        )
        if current is None:
            logger.warning(
                f"(U) {db_user.tg_user_id} - Rich: ДЗ {deadline_id} больше нет в списке"
            )
            await callback.answer("Задание больше не доступно.", show_alert=True)
            return
        changed = await _set_task_status(
            db_user.tg_user_id, deadline_id, target, surface="rich"
        )
    except Exception:
        logger.exception(
            f"(U) {db_user.tg_user_id} - Не удалось изменить отметку ДЗ {deadline_id}"
        )
        await callback.answer(
            "Не удалось обновить отметку. Попробуйте позже.", show_alert=True
        )
        return
    await callback.answer(_task_status_answer(target, changed))
    await send_deadlines_list(
        callback.message,
        db_user,
        days,
        hide_done=hide_done,
        edit=True,
        page=page,
        open_task_id=deadline_id,
    )


@router.callback_query(F.data.startswith("rich_toggle_"))
async def callback_old_rich_toggle(callback: CallbackQuery):
    await callback.answer("Кнопка устарела. Откройте дедлайны заново.", show_alert=True)


@router.callback_query(F.data == "divider_ignore")
async def callback_divider_ignore(callback: CallbackQuery):
    """Обработчик нажатия на разделитель (ничего не делает)"""
    await callback.answer()


def register_task_handlers(dp):
    """Регистрация handlers для задач (tasks/deadlines)"""
    dp.include_router(router)
