import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from src.bot.handlers import tasks
from src.bot.presentation import build_rich_deadlines, build_rich_deadlines_keyboard


def test_rich_deadlines_contains_table_details_and_buttons() -> None:
    item = {
        "deadline": SimpleNamespace(
            id=1001,
            hw_name="HW <1>",
            source_link="https://example.com/hw",
            note="Примечание",
            soft_deadline_ts=datetime.now(UTC) + timedelta(days=1),
            hard_deadline_ts=datetime.now(UTC) + timedelta(days=2),
        ),
        "subject": SimpleNamespace(name="SQL"),
        "nearest_deadline": datetime.now(UTC) + timedelta(days=1),
        "deadline_type": "soft",
        "is_done": False,
    }

    payload = build_rich_deadlines([item], 7, True).model_dump(
        mode="json", exclude_none=True
    )
    block_types = [block["type"] for block in payload["blocks"]]

    assert "table" in block_types
    assert "details" in block_types
    assert "buttons" not in block_types
    assert payload["blocks"][0]["text"] == "Дедлайны на 7 дней"
    assert payload["skip_entity_detection"] is True
    table = next(block for block in payload["blocks"] if block["type"] == "table")
    assert [cell["text"] for cell in table["cells"][0]] == [
        "Дисциплина",
        "Задание",
        "Дедлайн",
    ]
    assert table["cells"][1][0]["text"] == "SQL"
    assert table["cells"][1][1]["text"] == "HW <1>"
    details = next(block for block in payload["blocks"] if block["type"] == "details")
    assert details["summary"] == "HW <1>"
    details_text = details["blocks"][0]["text"]
    assert "SQL" not in str(details_text)
    assert "HW <1>" not in str(details_text)
    assert "🔴 " in details_text
    assert "💬 " in details_text
    assert len(details["blocks"]) == 2
    action = details["blocks"][1]
    assert action["type"] == "buttons"
    assert action["buttons"][0]["text"] == "✅ Отметить выполненным"
    assert action["buttons"][0]["callback_data"] == "rich_set_1001_done_7_0_h1"
    assert not any(
        button.get("callback_data", "").startswith("rich_set_")
        for block in payload["blocks"]
        if block["type"] == "buttons"
        for button in block["buttons"]
    )
    serialized = json.dumps(payload, ensure_ascii=False)
    assert '"date_time_format": "dt"' in serialized
    assert "dd.MM.yyyy HH:mm" not in serialized
    assert "Мягкий:" not in serialized and "Жёсткий:" not in serialized
    assert "Комментарий:" not in serialized and "Статус:" not in serialized
    keyboard = build_rich_deadlines_keyboard([item], 7, True)
    assert len(keyboard.inline_keyboard[0]) == 3
    assert keyboard.inline_keyboard[0][0].callback_data == "rich_current_7"
    assert keyboard.inline_keyboard[-1][0].callback_data == "back_to_menu"
    assert not any(
        button.callback_data and button.callback_data.startswith("mark_done_all_")
        for row in keyboard.inline_keyboard
        for button in row
    )
    footer = next(block for block in payload["blocks"] if block["type"] == "footer")
    assert footer["text"] == "Всего: 1"


def test_rich_pagination_appears_only_with_multiple_pages() -> None:
    deadline = datetime.now(UTC) + timedelta(days=1)
    items = [
        {
            "deadline": SimpleNamespace(
                id=i,
                hw_name=f"Работа {i}",
                source_link=None,
                note=None,
                soft_deadline_ts=None,
                hard_deadline_ts=deadline,
            ),
            "subject": SimpleNamespace(name="SQL"),
            "nearest_deadline": deadline,
            "deadline_type": "hard",
            "is_done": False,
        }
        for i in range(16)
    ]
    page = build_rich_deadlines(items, 15, False).model_dump(
        mode="json", exclude_none=True
    )
    footer = next(block for block in page["blocks"] if block["type"] == "footer")
    assert footer["text"] == "Всего: 16 · Страница 1/2"
    keyboard = build_rich_deadlines_keyboard(items, 15, False)
    assert any(
        button.callback_data == "rich_deadlines_15_1_h0"
        for row in keyboard.inline_keyboard
        for button in row
    )


def test_rich_completed_task_has_clear_reverse_action() -> None:
    deadline = datetime.now(UTC) + timedelta(days=1)
    item = {
        "deadline": SimpleNamespace(
            id=2,
            hw_name="Работа",
            source_link=None,
            note=None,
            soft_deadline_ts=None,
            hard_deadline_ts=deadline,
        ),
        "subject": SimpleNamespace(name="Дисциплина"),
        "nearest_deadline": deadline,
        "deadline_type": "hard",
        "is_done": True,
    }
    payload = build_rich_deadlines([item], 15, False).model_dump(
        mode="json", exclude_none=True
    )
    table = next(block for block in payload["blocks"] if block["type"] == "table")
    assert table["cells"][1][1]["text"] == "✅ Работа"
    assert table["cells"][1][2]["text"][0] == "🔴"
    details = next(block for block in payload["blocks"] if block["type"] == "details")
    assert details["summary"] == "✅ Работа"
    action = details["blocks"][-1]
    assert action["buttons"][0]["text"] == "↩️ Вернуть в работу"
    assert action["buttons"][0]["callback_data"] == "rich_set_2_work_15_0_h0"
    reopened = build_rich_deadlines([item], 15, False, open_task_id=2).model_dump(
        mode="json", exclude_none=True
    )
    reopened_details = next(
        block for block in reopened["blocks"] if block["type"] == "details"
    )
    assert reopened_details["is_open"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("was_done", "expected_method"),
    [
        (False, "set_done"),
        (True, "set_not_done"),
    ],
)
async def test_rich_set_changes_status_and_refreshes_message(
    monkeypatch, was_done, expected_method
) -> None:
    calls = []

    class FakeMessage:
        pass

    class FakeCallback:
        data = f"rich_set_2_{'work' if was_done else 'done'}_15_1_h0"
        message = FakeMessage()

        async def answer(self, text=None, **kwargs):
            calls.append(("answer", text, kwargs))

    async def get_deadlines(*_args, **_kwargs):
        return [{"deadline": SimpleNamespace(id=2), "is_done": was_done}]

    async def set_done(*_args, **_kwargs):
        calls.append(("set_done",))
        return True

    async def set_not_done(*_args, **_kwargs):
        calls.append(("set_not_done",))
        return True

    async def send_list(*_args, **kwargs):
        calls.append(("refresh", kwargs))

    monkeypatch.setattr(tasks, "Message", FakeMessage)
    monkeypatch.setattr(tasks.deadline_service, "get_user_deadlines", get_deadlines)
    monkeypatch.setattr(tasks.task_status_service, "set_done", set_done)
    monkeypatch.setattr(tasks.task_status_service, "set_not_done", set_not_done)
    monkeypatch.setattr(tasks, "send_deadlines_list", send_list)

    await tasks.callback_rich_set(FakeCallback(), SimpleNamespace(tg_user_id=123))

    assert (expected_method,) in calls
    assert ("answer", None, {}) in calls
    assert (
        "refresh",
        {"hide_done": False, "edit": True, "page": 1, "open_task_id": 2},
    ) in calls


@pytest.mark.asyncio
async def test_repeated_rich_button_never_reverses_the_action(monkeypatch) -> None:
    calls = []

    class FakeMessage:
        pass

    class FakeCallback:
        data = "rich_set_2_done_7_0_h0"
        message = FakeMessage()

        async def answer(self, text=None, **_kwargs):
            calls.append(("answer", text))

    async def get_deadlines(*_args, **_kwargs):
        return [{"deadline": SimpleNamespace(id=2), "is_done": True}]

    async def set_done(*_args, **_kwargs):
        calls.append(("set_done",))
        return False

    async def set_not_done(*_args, **_kwargs):
        raise AssertionError("Повторное нажатие не должно возвращать ДЗ в работу")

    async def send_list(*_args, **_kwargs):
        calls.append(("refresh",))

    monkeypatch.setattr(tasks, "Message", FakeMessage)
    monkeypatch.setattr(tasks.deadline_service, "get_user_deadlines", get_deadlines)
    monkeypatch.setattr(tasks.task_status_service, "set_done", set_done)
    monkeypatch.setattr(tasks.task_status_service, "set_not_done", set_not_done)
    monkeypatch.setattr(tasks, "send_deadlines_list", send_list)

    await tasks.callback_rich_set(FakeCallback(), SimpleNamespace(tg_user_id=123))

    assert calls == [
        ("set_done",),
        ("answer", None),
        ("refresh",),
    ]
