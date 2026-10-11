from types import SimpleNamespace
from unittest.mock import ANY

import pytest
from aiogram.dispatcher.event.bases import UNHANDLED

import src.bot.middlewares.callback_audit as audit_module


@pytest.mark.asyncio
async def test_every_callback_is_logged_before_handler(monkeypatch) -> None:
    events = []

    async def record_event(**kwargs):
        events.append(("event", kwargs))

    class FakeLogger:
        def info(self, message):
            events.append(("log", message))

    async def handler(event, data):
        events.append(("handle", event.data, data))
        return "ok"

    monkeypatch.setattr(audit_module, "logger", FakeLogger())
    monkeypatch.setattr(audit_module, "record_user_action_event", record_event)
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        data="rich_set_7_done_15_0_h1",
        game_short_name=None,
        message=SimpleNamespace(
            message_id=9, chat=SimpleNamespace(id=17, type="private")
        ),
    )

    result = await audit_module.CallbackAuditMiddleware()(
        handler, callback, {"key": "value"}
    )

    assert result == "ok"
    assert events == [
        ("log", "(U) 42 - Кнопка: 'rich_set_7_done_15_0_h1' chat=17 message=9"),
        ("handle", "rich_set_7_done_15_0_h1", {"key": "value"}),
        (
            "event",
            {
                "user_id": 42,
                "event_name": "button_clicked",
                "occurred_at": ANY,
                "surface": "private",
                "chat_id": 17,
                "message_id": 9,
                "details": {
                    "callback_data": "rich_set_7_done_15_0_h1",
                    "button_type": "rich_set_{id}_done_{id}_{id}_h1",
                },
                "outcome": "handled",
            },
        ),
    ]


@pytest.mark.asyncio
async def test_unmatched_button_is_recorded(monkeypatch) -> None:
    records = []

    async def record_event(**kwargs):
        records.append(kwargs)

    async def handler(_event, _data):
        return UNHANDLED

    monkeypatch.setattr(audit_module, "record_user_action_event", record_event)
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        data="unknown_button",
        game_short_name=None,
        message=None,
    )

    assert (
        await audit_module.CallbackAuditMiddleware()(handler, callback, {}) is UNHANDLED
    )
    assert records[0]["outcome"] == "unhandled"
    assert records[0]["details"] == {
        "callback_data": "unknown_button",
        "button_type": "unknown_button",
    }


@pytest.mark.asyncio
async def test_failed_button_is_recorded_and_error_propagates(monkeypatch) -> None:
    records = []

    async def record_event(**kwargs):
        records.append(kwargs)

    async def handler(_event, _data):
        raise RuntimeError("handler failed")

    monkeypatch.setattr(audit_module, "record_user_action_event", record_event)
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        data="broken_button",
        game_short_name=None,
        message=None,
    )

    with pytest.raises(RuntimeError, match="handler failed"):
        await audit_module.CallbackAuditMiddleware()(handler, callback, {})
    assert records[0]["outcome"] == "failed"
