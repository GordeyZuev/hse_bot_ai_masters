from types import SimpleNamespace

import pytest

from src.bot.handlers import tasks


@pytest.mark.asyncio
async def test_old_quick_button_cannot_reverse_newer_status(monkeypatch) -> None:
    calls = []

    class FakeCallback:
        data = "quick_set_42_done_7_h0_p0"
        message = SimpleNamespace()

        async def answer(self, text, **_kwargs):
            calls.append(("answer", text))

    async def get_deadlines(*_args, **_kwargs):
        return [{"deadline": SimpleNamespace(id=42), "is_done": True}]

    async def set_done(*_args, **_kwargs):
        calls.append(("set_done",))
        return False

    async def set_not_done(*_args, **_kwargs):
        raise AssertionError("Старая кнопка не должна отменять выполненность")

    async def refresh(*_args, **_kwargs):
        calls.append(("refresh",))

    monkeypatch.setattr(tasks.deadline_service, "get_user_deadlines", get_deadlines)
    monkeypatch.setattr(tasks.task_status_service, "set_done", set_done)
    monkeypatch.setattr(tasks.task_status_service, "set_not_done", set_not_done)
    monkeypatch.setattr(tasks, "send_deadlines_list_for_checking", refresh)

    await tasks.callback_quick_set(FakeCallback(), SimpleNamespace(tg_user_id=1))
    assert calls == [
        ("set_done",),
        ("answer", "Задание уже выполнено"),
        ("refresh",),
    ]


@pytest.mark.asyncio
async def test_old_card_button_cannot_reverse_newer_status(monkeypatch) -> None:
    calls = []

    class FakeCallback:
        data = "task_card_set_42_done_7_0_h0"
        message = SimpleNamespace()

        async def answer(self, text, **_kwargs):
            calls.append(("answer", text))

    async def card_payload(*_args, **_kwargs):
        return "card", None, True

    async def set_done(*_args, **_kwargs):
        calls.append(("set_done",))
        return False

    async def set_not_done(*_args, **_kwargs):
        raise AssertionError("Старая кнопка не должна отменять выполненность")

    async def edit(*_args, **_kwargs):
        calls.append(("refresh",))

    monkeypatch.setattr(tasks, "_task_card_payload", card_payload)
    monkeypatch.setattr(tasks.task_status_service, "set_done", set_done)
    monkeypatch.setattr(tasks.task_status_service, "set_not_done", set_not_done)
    monkeypatch.setattr(tasks, "safe_edit_message", edit)

    await tasks.callback_task_card_set(FakeCallback(), SimpleNamespace(tg_user_id=1))
    assert calls == [
        ("set_done",),
        ("answer", "Задание уже выполнено"),
        ("refresh",),
    ]


@pytest.mark.asyncio
async def test_old_subject_button_cannot_reverse_newer_status(monkeypatch) -> None:
    calls = []

    class FakeCallback:
        data = "subject_task_set_42_done_5_7_h0"
        message = SimpleNamespace()

        async def answer(self, text, **_kwargs):
            calls.append(("answer", text))

    async def get_deadlines(*_args, **_kwargs):
        return [
            {
                "deadline": SimpleNamespace(id=42),
                "subject": SimpleNamespace(id=5),
                "is_done": True,
            }
        ]

    async def set_done(*_args, **_kwargs):
        calls.append(("set_done",))
        return False

    async def set_not_done(*_args, **_kwargs):
        raise AssertionError("Старая кнопка не должна отменять выполненность")

    async def refresh(*_args, **_kwargs):
        calls.append(("refresh",))

    monkeypatch.setattr(tasks.deadline_service, "get_user_deadlines", get_deadlines)
    monkeypatch.setattr(tasks.task_status_service, "set_done", set_done)
    monkeypatch.setattr(tasks.task_status_service, "set_not_done", set_not_done)
    monkeypatch.setattr(tasks, "show_subject_task_checks", refresh)

    await tasks.callback_subject_task_set(FakeCallback(), SimpleNamespace(tg_user_id=1))
    assert calls == [
        ("set_done",),
        ("answer", "Задание уже выполнено"),
        ("refresh",),
    ]
