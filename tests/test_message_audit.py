from types import SimpleNamespace

import pytest

import src.bot.middlewares.message_audit as audit_module


@pytest.mark.asyncio
async def test_message_audit_records_type_or_command_without_private_text(monkeypatch):
    logs = []
    records = []

    async def record_event(**kwargs):
        records.append(kwargs)

    monkeypatch.setattr(audit_module, "logger", SimpleNamespace(info=logs.append))
    monkeypatch.setattr(audit_module, "record_user_action_event", record_event)

    async def handler(_event, _data):
        return "handled"

    middleware = audit_module.MessageAuditMiddleware()
    for text, content_type in (
        ("/start private payload", "text"),
        ("private payload", "text"),
        (None, "location"),
    ):
        event = SimpleNamespace(
            from_user=SimpleNamespace(id=42),
            text=text,
            content_type=content_type,
            chat=SimpleNamespace(id=99, type="private"),
            message_id=7,
        )
        assert await middleware(handler, event, {}) == "handled"

    assert logs == [
        "(U) 42 - Входящее команда /start",
        "(U) 42 - Входящее сообщение text",
        "(U) 42 - Входящее сообщение location",
    ]
    assert all("private payload" not in log for log in logs)
    assert [record["details"] for record in records] == [
        {"command": "/start"},
        {"content_type": "text"},
        {"content_type": "location"},
    ]
    assert all(record["outcome"] == "handled" for record in records)
