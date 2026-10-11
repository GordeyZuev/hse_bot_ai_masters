from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText

from src.bot.handlers import tasks
from src.bot.handlers.tasks import (
    _compact_deadline_pages,
    _edit_or_send,
    _task_card_payload,
    send_deadlines_list,
)
from src.bot.services.deadline_service import deadline_service
from src.bot.services.notification_service import notification_service


def _item():
    soft = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
    return {
        "deadline": SimpleNamespace(
            id=42,
            hw_name="Проект <ML>",
            source_link="https://example.com/hw",
            note="Комментарий <важный>",
            soft_deadline_ts=soft,
            hard_deadline_ts=soft + timedelta(days=2),
        ),
        "subject": SimpleNamespace(name="Машинное обучение & SQL"),
        "nearest_deadline": soft,
        "deadline_type": "soft",
        "is_done": False,
    }


@pytest.mark.asyncio
async def test_card_shows_both_dates_and_stays_on_same_page(monkeypatch) -> None:
    async def get_user_deadlines(*_args, **_kwargs):
        return [_item()]

    monkeypatch.setattr(deadline_service, "get_user_deadlines", get_user_deadlines)
    user = SimpleNamespace(tg_user_id=1, timezone="Europe/Moscow")
    payload = await _task_card_payload(user, 42, 7, 2, True)

    assert payload is not None
    text, markup, is_done = payload
    assert "Мягкий дедлайн" in text and "Жёсткий дедлайн" in text
    assert "&lt;важный&gt;" in text
    assert is_done is False
    callbacks = [
        button.callback_data for row in markup.inline_keyboard for button in row
    ]
    assert "task_card_set_42_done_7_2_h1" in callbacks
    assert "deadlines_page_7_2_h1" in callbacks


@pytest.mark.asyncio
async def test_standard_list_preserves_original_layout_and_edits_one_message(
    monkeypatch,
) -> None:
    async def get_user_deadlines(*_args, **_kwargs):
        return [_item()]

    async def get_settings(*_args, **_kwargs):
        raise AssertionError("Настройки Rich не нужны для стандартного режима")

    class FakeMessage:
        def __init__(self):
            self.edits = []

        async def edit_text(self, text, **kwargs):
            self.edits.append((text, kwargs))

    monkeypatch.setenv("RICH_MESSAGES_ENABLED", "false")
    monkeypatch.setattr(deadline_service, "get_user_deadlines", get_user_deadlines)
    monkeypatch.setattr(
        notification_service, "get_user_notification_settings", get_settings
    )
    message = FakeMessage()
    user = SimpleNamespace(tg_user_id=1, timezone="Europe/Moscow")

    await send_deadlines_list(message, user, 7, edit=True)

    assert len(message.edits) == 1
    text, kwargs = message.edits[0]
    assert "Проект &lt;ML&gt;" in text
    assert "Машинное обучение &amp; SQL" in text
    rows = kwargs["reply_markup"].inline_keyboard
    assert len(rows[0]) == 3
    assert [row[0].callback_data for row in rows[1:]] == [
        "toggle_hide_done_7_h1",
        "mark_done_all_7_h1",
        "back_to_menu",
    ]
    assert "quick_subjects" not in [
        button.callback_data for row in rows for button in row
    ]


@pytest.mark.asyncio
async def test_rich_list_edits_one_message_with_global_keyboard(monkeypatch) -> None:
    async def get_user_deadlines(*_args, **_kwargs):
        return [_item()]

    async def get_settings(*_args, **_kwargs):
        return SimpleNamespace(display_mode="rich")

    async def record_event(**_kwargs):
        return None

    class FakeMessage:
        def __init__(self):
            self.edits = []

        async def edit_text(self, text, **kwargs):
            self.edits.append((text, kwargs))

    monkeypatch.setenv("RICH_MESSAGES_ENABLED", "true")
    monkeypatch.setattr(deadline_service, "get_user_deadlines", get_user_deadlines)
    monkeypatch.setattr(
        notification_service, "get_user_notification_settings", get_settings
    )
    monkeypatch.setattr(tasks, "record_user_action_event", record_event)
    message = FakeMessage()

    await send_deadlines_list(
        message, SimpleNamespace(tg_user_id=1, timezone="Europe/Moscow"), 7, edit=True
    )

    assert len(message.edits) == 1
    text, kwargs = message.edits[0]
    assert text is None
    assert kwargs["rich_message"].blocks
    rows = kwargs["reply_markup"].inline_keyboard
    assert len(rows[0]) == 3
    assert rows[-1][0].callback_data == "back_to_menu"


@pytest.mark.asyncio
async def test_repeated_rich_render_does_not_fall_back_to_compact(monkeypatch) -> None:
    async def get_user_deadlines(*_args, **_kwargs):
        return [_item()]

    async def get_settings(*_args, **_kwargs):
        return SimpleNamespace(display_mode="rich")

    async def record_event(**_kwargs):
        return None

    class FakeMessage:
        async def edit_text(self, _text, **_kwargs):
            raise TelegramBadRequest(
                method=EditMessageText(chat_id=1, message_id=1, text="test"),
                message="message is not modified",
            )

        async def answer(self, *_args, **_kwargs):
            raise AssertionError("Rich не должен превращаться в обычный список")

    monkeypatch.setenv("RICH_MESSAGES_ENABLED", "true")
    monkeypatch.setattr(deadline_service, "get_user_deadlines", get_user_deadlines)
    monkeypatch.setattr(
        notification_service, "get_user_notification_settings", get_settings
    )
    monkeypatch.setattr(tasks, "record_user_action_event", record_event)

    await send_deadlines_list(
        FakeMessage(),
        SimpleNamespace(tg_user_id=1, timezone="Europe/Moscow"),
        7,
        edit=True,
    )


@pytest.mark.asyncio
async def test_edit_falls_back_to_new_message_only_if_original_is_gone() -> None:
    class FakeMessage:
        def __init__(self, error):
            self.error = error
            self.answers = []

        async def edit_text(self, _text, **_kwargs):
            raise TelegramBadRequest(
                method=EditMessageText(chat_id=1, message_id=1, text="test"),
                message=self.error,
            )

        async def answer(self, text, **kwargs):
            self.answers.append((text, kwargs))

    deleted = FakeMessage("message to edit not found")
    await _edit_or_send(deleted, "Карточка")
    assert deleted.answers == [("Карточка", {})]

    unchanged = FakeMessage("message is not modified")
    await _edit_or_send(unchanged, "Карточка")
    assert unchanged.answers == []


def test_compact_list_paginates_without_changing_short_list_layout() -> None:
    items = []
    for task_id in range(1, 61):
        item = _item()
        item["deadline"] = SimpleNamespace(
            id=task_id,
            hw_name="Домашнее задание по анализу данных",
            source_link=None,
        )
        items.append(item)

    pages = _compact_deadline_pages(items, 500, "Europe/Moscow", True)
    assert len(pages) > 1
    assert all(len(page) < 4096 for page in pages)
    assert "<b>1. Машинное обучение &amp; SQL</b>" in pages[0]
    assert "<b>60. Машинное обучение &amp; SQL</b>" in pages[-1]
    assert all("Страница " in page for page in pages)


@pytest.mark.asyncio
async def test_compact_next_page_edits_same_message(monkeypatch) -> None:
    items = []
    for task_id in range(1, 61):
        item = _item()
        item["deadline"] = SimpleNamespace(
            id=task_id, hw_name="Домашнее задание", source_link=None
        )
        items.append(item)

    async def get_user_deadlines(*_args, **_kwargs):
        return items

    class FakeMessage:
        def __init__(self):
            self.edits = []

        async def edit_text(self, text, **kwargs):
            self.edits.append((text, kwargs))

    monkeypatch.setenv("RICH_MESSAGES_ENABLED", "false")
    monkeypatch.setattr(deadline_service, "get_user_deadlines", get_user_deadlines)
    message = FakeMessage()
    user = SimpleNamespace(tg_user_id=1, timezone="Europe/Moscow")
    await send_deadlines_list(message, user, 500, edit=True, page=1)

    assert len(message.edits) == 1
    text, kwargs = message.edits[0]
    assert "Страница 2/" in text
    callbacks = [
        button.callback_data
        for row in kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert "deadlines_page_500_0_h1" in callbacks
    assert "back_to_menu" in callbacks
