from types import SimpleNamespace

import pytest
from sqlalchemy.sql.dml import Delete, Insert

import src.bot.services.task_status_service as status_module


@pytest.mark.asyncio
async def test_status_changes_are_logged_after_commit(monkeypatch) -> None:
    events = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, statement):
            if isinstance(statement, (Insert, Delete)):
                return SimpleNamespace(scalar_one_or_none=lambda: 42)
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

        def add(self, value):
            events.append(("event", value.event_name, value.surface))

        async def commit(self):
            events.append("commit")

        async def get(self, _model, _id):
            return None

    class FakeLogger:
        def info(self, message):
            events.append(("info", message))

        def debug(self, _message):
            pass

    monkeypatch.setattr(status_module.db_manager, "async_session", FakeSession)
    monkeypatch.setattr(status_module, "logger", FakeLogger())

    assert (
        await status_module.task_status_service.set_done(42, 7, surface="rich") is True
    )
    assert await status_module.task_status_service.set_not_done(42, 7) is True

    assert events == [
        ("event", "task_completed", "rich"),
        "commit",
        ("info", "(U) 42 - ДЗ 7 отмечено выполненным"),
        ("event", "task_returned_to_work", None),
        "commit",
        ("info", "(U) 42 - ДЗ 7 возвращено в работу"),
    ]


@pytest.mark.asyncio
async def test_failed_commit_is_not_logged_as_completed_action(monkeypatch) -> None:
    messages = []

    class FailingSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, statement):
            if isinstance(statement, Insert):
                return SimpleNamespace(scalar_one_or_none=lambda: 42)
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

        def add(self, _value):
            pass

        async def commit(self):
            raise RuntimeError("DB unavailable")

    monkeypatch.setattr(status_module.db_manager, "async_session", FailingSession)
    monkeypatch.setattr(
        status_module,
        "logger",
        SimpleNamespace(info=messages.append),
    )

    with pytest.raises(RuntimeError, match="DB unavailable"):
        await status_module.task_status_service.set_done(42, 7)

    assert messages == []


@pytest.mark.asyncio
async def test_repeated_status_request_does_not_log_or_create_event(
    monkeypatch,
) -> None:
    events = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, statement):
            if isinstance(statement, (Insert, Delete)):
                return SimpleNamespace(scalar_one_or_none=lambda: None)
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

        def add(self, _value):
            events.append("event")

        async def commit(self):
            events.append("commit")

    monkeypatch.setattr(status_module.db_manager, "async_session", FakeSession)
    monkeypatch.setattr(
        status_module,
        "logger",
        SimpleNamespace(info=lambda _message: events.append("log")),
    )

    assert await status_module.task_status_service.set_done(42, 7) is False
    assert await status_module.task_status_service.set_not_done(42, 7) is False
    assert events == ["commit", "commit"]
