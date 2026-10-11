from __future__ import annotations

from datetime import UTC, datetime
from math import ceil
from typing import Any, cast
from zoneinfo import ZoneInfo

from aiogram.enums import ButtonStyle
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputRichBlockButtons,
    InputRichBlockDetails,
    InputRichBlockDivider,
    InputRichBlockFooter,
    InputRichBlockParagraph,
    InputRichBlockSectionHeading,
    InputRichBlockTable,
    InputRichMessage,
    RichBlockTableCell,
    RichMessageButton,
    RichTextDateTime,
    RichTextUrl,
)

from src.utils.notification_formatting import format_time_remaining


PAGE_SIZE = 15


def rich_page_count(items: list[dict[str, Any]]) -> int:
    return max(1, ceil(len(items) / PAGE_SIZE))


def _cell(text: Any, *, header: bool = False) -> RichBlockTableCell:
    return RichBlockTableCell(
        align="left", valign="middle", text=text, is_header=header
    )


def _deadline_timestamp(item: dict[str, Any]) -> datetime:
    return cast("datetime", item["nearest_deadline"])


def _deadline_text(timestamp: datetime, tz_name: str) -> RichTextDateTime:
    return RichTextDateTime(
        text=timestamp.astimezone(ZoneInfo(tz_name)).strftime("%d.%m %H:%M"),
        unix_time=int(timestamp.timestamp()),
        date_time_format="dt",
    )


def _preview(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def build_rich_deadlines(
    items: list[dict[str, Any]],
    days: int,
    hide_done: bool,
    page: int = 0,
    tz_name: str = "Europe/Moscow",
    open_task_id: int | None = None,
) -> InputRichMessage:
    """Build a mobile-friendly Rich Message from the shared deadline DTO."""
    pages = rich_page_count(items)
    page = min(max(page, 0), pages - 1)
    visible = items[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    blocks: list[Any] = [
        InputRichBlockSectionHeading(
            text=(f"Дедлайны на {days} дней" if days < 500 else "Все дедлайны"),
            size=2,
        )
    ]

    if not visible:
        blocks.append(InputRichBlockParagraph(text="Актуальных дедлайнов нет 🎉"))
    else:
        rows = [
            [
                _cell("Дисциплина", header=True),
                _cell("Задание", header=True),
                _cell("Дедлайн", header=True),
            ]
        ]
        for item in visible:
            task = item["deadline"]
            subject = item["subject"]
            icon = "🟡" if item.get("deadline_type") == "soft" else "🔴"
            task_name = _preview(task.hw_name or "Без названия", 32)
            rows.append(
                [
                    _cell(_preview(subject.name, 25)),
                    _cell(f"✅ {task_name}" if item.get("is_done") else task_name),
                    _cell(
                        [icon, " ", _deadline_text(_deadline_timestamp(item), tz_name)]
                    ),
                ]
            )
        blocks.append(
            InputRichBlockTable(
                cells=rows, is_bordered=True, is_striped=True, is_compact=True
            )
        )
        blocks.append(InputRichBlockDivider())

        now = datetime.now(UTC)
        for item in visible:
            task = item["deadline"]
            text: list[Any] = []
            if task.source_link:
                text.extend(
                    ["🔗 ", RichTextUrl(text="Открыть задание", url=task.source_link)]
                )
            nearest = _deadline_timestamp(item)
            remaining = format_time_remaining(nearest, now)
            if remaining:
                text.extend(["\n" if text else "", f"⏳ {remaining}"])
            for timestamp, icon in (
                (task.soft_deadline_ts, "🟡"),
                (task.hard_deadline_ts, "🔴"),
            ):
                if timestamp and timestamp != nearest:
                    text.extend(
                        [
                            "\n" if text else "",
                            f"{icon} ",
                            _deadline_text(timestamp, tz_name),
                        ]
                    )
            if task.note:
                text.extend(["\n" if text else "", "💬 ", task.note])
            summary: Any = task.hw_name or "Без названия"
            if item.get("is_done"):
                summary = f"✅ {summary}"
            detail_blocks: list[Any] = []
            if text:
                detail_blocks.append(InputRichBlockParagraph(text=text))
            detail_blocks.append(
                InputRichBlockButtons(
                    buttons=[
                        RichMessageButton(
                            text=(
                                "↩️ Вернуть в работу"
                                if item.get("is_done")
                                else "✅ Отметить выполненным"
                            ),
                            callback_data=f"rich_set_{task.id}_{'work' if item.get('is_done') else 'done'}_{days}_{page}_h{int(hide_done)}",
                            style="primary" if item.get("is_done") else "success",
                        )
                    ],
                    align="left",
                )
            )
            blocks.append(
                InputRichBlockDetails(
                    summary=summary,
                    blocks=detail_blocks,
                    is_open=task.id == open_task_id,
                )
            )

    footer = f"Всего: {len(items)}"
    if pages > 1:
        footer += f" · Страница {page + 1}/{pages}"
    blocks.append(InputRichBlockFooter(text=footer))
    return InputRichMessage(blocks=blocks, skip_entity_detection=True)


def build_rich_deadlines_keyboard(
    items: list[dict[str, Any]], days: int, hide_done: bool, page: int = 0
) -> InlineKeyboardMarkup:
    """Global navigation stays below the message; task actions stay in details."""
    pages = rich_page_count(items)
    page = min(max(page, 0), pages - 1)
    rows: list[list[InlineKeyboardButton]] = []
    period_buttons = []
    for period, label in ((7, "7 дней"), (15, "15 дней"), (500, "Все")):
        period_buttons.append(
            InlineKeyboardButton(
                text=f"🔷 {label}" if period == days else label,
                callback_data=(
                    f"rich_current_{period}"
                    if period == days
                    else f"rich_deadlines_{period}_0_h{int(hide_done)}"
                ),
                style=ButtonStyle.PRIMARY if period == days else None,
            )
        )
    rows.append(period_buttons)

    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton(
                text="← Назад",
                callback_data=f"rich_deadlines_{days}_{page - 1}_h{int(hide_done)}",
            )
        )
    if page + 1 < pages:
        navigation.append(
            InlineKeyboardButton(
                text="Далее →",
                callback_data=f"rich_deadlines_{days}_{page + 1}_h{int(hide_done)}",
            )
        )
    if navigation:
        rows.append(navigation)

    rows.append(
        [
            InlineKeyboardButton(
                text="Скрыть выполненные" if not hide_done else "Показать выполненные",
                callback_data=f"rich_deadlines_{days}_0_h{int(not hide_done)}",
            )
        ]
    )
    rows.append([InlineKeyboardButton(text="Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
