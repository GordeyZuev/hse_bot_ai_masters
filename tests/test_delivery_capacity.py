from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendMessage

from src.bot.services.chat_notification_sender import ChatNotificationSender
from src.bot.services.notification_sender import NotificationSender
from src.bot.services.scheduled_notification_sender import ScheduledNotificationSender
from src.core.database import db_manager
from src.utils.telegram_text import MessageTooLongError


@pytest.mark.asyncio
async def test_one_user_delivery_run_drains_nine_hundred_due_rows(monkeypatch) -> None:
    sender = ScheduledNotificationSender()
    remaining = [SimpleNamespace(id=i, user_id=i) for i in range(900)]
    calls = 0

    async def claim(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        batch = remaining[:100]
        del remaining[:100]
        return batch

    async def process(_bot, _user_id, notifications, stats):
        stats["sent"] += len(notifications)
        stats["total_processed"] += len(notifications)

    monkeypatch.setattr(db_manager, "get_scheduled_notifications_for_delivery", claim)
    monkeypatch.setattr(sender, "_process_user_notifications", process)
    result = await sender.send_scheduled_notifications(object())
    assert result["sent"] == 900
    assert calls == 10  # Nine full batches and one empty claim.


@pytest.mark.asyncio
async def test_one_chat_delivery_run_drains_more_than_one_batch(monkeypatch) -> None:
    sender = ChatNotificationSender()
    remaining = [SimpleNamespace(chat_id=i, topic_id=None) for i in range(230)]
    calls = 0

    async def claim():
        nonlocal calls
        calls += 1
        batch = remaining[:100]
        del remaining[:100]
        return batch

    async def process(_bot, _chat_id, _topic_id, notifications, stats):
        stats["sent"] += len(notifications)
        stats["total_processed"] += len(notifications)

    monkeypatch.setattr(sender, "_get_scheduled_notifications_for_delivery", claim)
    monkeypatch.setattr(sender, "_process_chat_notifications", process)
    result = await sender.send_scheduled_chat_notifications(object())
    assert result["sent"] == 230
    assert calls == 4


@pytest.mark.asyncio
async def test_long_user_group_is_split_only_when_text_is_too_long(monkeypatch) -> None:
    sender = ScheduledNotificationSender()
    notifications = [SimpleNamespace(id=i, attempt_count=1) for i in range(12)]
    sent_sizes = []
    statuses = []

    async def send(_bot, _user_id, group):
        if len(group) > 6:
            raise MessageTooLongError("oversize")
        sent_sizes.append(len(group))
        return len(sent_sizes) == 1

    async def update(ids, status, *_args, **_kwargs):
        statuses.append((ids, status))

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(sender, "_send_notifications_to_user", send)
    monkeypatch.setattr(db_manager, "update_notification_statuses", update)
    monkeypatch.setattr(
        "src.bot.services.scheduled_notification_sender.asyncio.sleep", no_sleep
    )
    stats = {"sent": 0, "failed": 0, "total_processed": 0}
    await sender._process_user_notifications(object(), 1, notifications, stats)

    assert sent_sizes == [6, 6]
    assert statuses == [(list(range(6)), "sent"), (list(range(6, 12)), "dead")]
    assert stats == {"sent": 6, "failed": 6, "total_processed": 12}


@pytest.mark.asyncio
async def test_immediate_update_retries_one_flood_error(monkeypatch) -> None:
    sender = NotificationSender()
    calls = []

    async def acquire():
        calls.append("limit")

    async def send(*_args, **_kwargs):
        calls.append("send")
        if calls.count("send") == 1:
            raise TelegramRetryAfter(
                method=SendMessage(chat_id=1, text="test"),
                message="Too Many Requests",
                retry_after=1,
            )
        return True

    async def no_sleep(_delay):
        calls.append("sleep")

    monkeypatch.setattr(
        "src.bot.services.notification_sender.telegram_rate_limiter.acquire", acquire
    )
    monkeypatch.setattr("src.bot.services.notification_sender.safe_send_message", send)
    monkeypatch.setattr("src.bot.services.notification_sender.asyncio.sleep", no_sleep)

    assert await sender._send_immediate_message(object(), 1, "text", object()) is True
    assert calls == ["limit", "send", "sleep", "limit", "send"]


@pytest.mark.asyncio
async def test_delivery_results_cannot_reactivate_cancelled_rows(monkeypatch) -> None:
    statements = []

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, statement):
            statements.append(statement)

        async def commit(self):
            return None

    monkeypatch.setattr(db_manager, "async_session", lambda: Session())
    await db_manager.update_notification_statuses([1], "sent")
    chat_sender = ChatNotificationSender()
    notification = SimpleNamespace(id=2, attempt_count=1)
    await chat_sender._mark_notifications_as_sent([notification])
    await chat_sender._mark_notifications_as_failed([notification])

    assert len(statements) == 3
    assert all("status =" in str(statement) for statement in statements)
    assert all(
        "processing" in statement.compile().params.values() for statement in statements
    )
