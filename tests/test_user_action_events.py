from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from src.core.models import UserActionEvent


def test_event_jsonb_default_matches_migration() -> None:
    sql = str(
        CreateTable(UserActionEvent.__table__).compile(dialect=postgresql.dialect())
    )
    assert "details JSONB DEFAULT '{}'::jsonb NOT NULL" in sql
    assert not UserActionEvent.__table__.foreign_keys
    assert {"chat_id", "message_id", "outcome"} <= set(
        UserActionEvent.__table__.columns.keys()
    )
