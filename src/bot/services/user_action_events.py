"""Durable, deliberately small event stream; diagnostic logs remain separate."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import db_manager
from src.core.models import UserActionEvent
from src.utils import get_logger


logger = get_logger()


def add_user_action_event(
    session: AsyncSession,
    *,
    user_id: int,
    event_name: str,
    occurred_at: datetime | None = None,
    surface: str | None = None,
    chat_id: int | None = None,
    message_id: int | None = None,
    outcome: str | None = None,
    subject_id: int | None = None,
    task_id: int | None = None,
    details: dict[str, int | str | bool] | None = None,
) -> None:
    """Add a successful action to the same transaction as its state change."""
    values = {
        "user_id": user_id,
        "event_name": event_name,
        "surface": surface,
        "chat_id": chat_id,
        "message_id": message_id,
        "outcome": outcome,
        "subject_id": subject_id,
        "task_id": task_id,
        "details": details or {},
    }
    if occurred_at is not None:
        values["occurred_at"] = occurred_at
    session.add(UserActionEvent(**values))


async def record_user_action_event(**kwargs) -> None:
    """Best-effort event for read-only screens and legacy separate transactions."""
    try:
        async with db_manager.async_session() as session:
            add_user_action_event(session, **kwargs)
            await session.commit()
    except Exception:
        logger.exception("Не удалось сохранить событие пользовательского действия")


async def cleanup_user_action_events(days_old: int = 365) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=days_old)
    async with db_manager.async_session() as session:
        result = await session.execute(
            delete(UserActionEvent).where(UserActionEvent.occurred_at < cutoff)
        )
        await session.commit()
        return result.rowcount or 0
