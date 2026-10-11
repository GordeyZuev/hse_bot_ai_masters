from types import SimpleNamespace

import pytest

from src.core.database import db_manager
from src.core.models import UserActionEvent


@pytest.mark.asyncio
async def test_setting_and_event_commit_together(monkeypatch) -> None:
    events = []
    settings = SimpleNamespace(is_active=True, last_modified=None)

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, _statement):
            return SimpleNamespace(scalar_one_or_none=lambda: settings)

        def add(self, value):
            events.append(("add", value))

        async def commit(self):
            events.append("commit")

        async def refresh(self, _value):
            pass

    monkeypatch.setattr(db_manager, "async_session", FakeSession)

    await db_manager.update_user_notification_settings(
        42,
        {"is_active": False},
        audit_details={"setting": "notifications_enabled", "enabled": False},
    )

    assert settings.is_active is False
    assert isinstance(events[0][1], UserActionEvent)
    assert events[0][1].details == {
        "setting": "notifications_enabled",
        "enabled": False,
    }
    assert events[1] == "commit"


@pytest.mark.asyncio
async def test_unchanged_setting_does_not_create_success_event(monkeypatch) -> None:
    events = []
    settings = SimpleNamespace(is_active=False, last_modified=None)

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, _statement):
            return SimpleNamespace(scalar_one_or_none=lambda: settings)

        def add(self, value):
            events.append(value)

        async def commit(self):
            pass

        async def refresh(self, _value):
            pass

    monkeypatch.setattr(db_manager, "async_session", FakeSession)

    await db_manager.update_user_notification_settings(
        42, {"is_active": False}, audit_details={"setting": "notifications_enabled"}
    )

    assert events == []
