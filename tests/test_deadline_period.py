from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from src.bot.services.deadline_service import deadline_service
from src.core.database import db_manager


@pytest.mark.asyncio
async def test_all_period_has_no_upper_date_bound(monkeypatch) -> None:
    statements = []

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, statement):
            statements.append(statement)
            return SimpleNamespace(fetchall=lambda: [])

    monkeypatch.setattr(db_manager, "async_session", lambda: Session())

    assert await deadline_service.get_user_deadlines(1, days=7) == []
    assert await deadline_service.get_user_deadlines(1, days=500) == []

    ordinary = str(statements[0].compile(dialect=postgresql.dialect()))
    all_future = str(statements[1].compile(dialect=postgresql.dialect()))
    assert "tasks.soft_deadline_ts <=" in ordinary
    assert "tasks.hard_deadline_ts <=" in ordinary
    assert "tasks.soft_deadline_ts <=" not in all_future
    assert "tasks.hard_deadline_ts <=" not in all_future
