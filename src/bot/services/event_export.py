"""Stream product events into bounded JSONL ZIP archives."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import and_, or_, select

from src.bot.services.log_export import MAX_EXPORT_PART_BYTES
from src.core.database import db_manager
from src.core.models import UserActionEvent


def _write_part(path: Path, content: bytes) -> None:
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(f"{path.stem}.jsonl", content)


async def iter_event_export(
    output_dir: Path, start: date, end: date
) -> AsyncIterator[Path]:
    """Yield small ZIP parts using keyset pages and short database sessions."""
    since = datetime.combine(start, time.min, tzinfo=UTC)
    until = datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC)
    part_number = 0
    content = bytearray()
    last_time = None
    last_id = None

    async def flush() -> Path:
        nonlocal part_number
        part_number += 1
        target = output_dir / f"events-{part_number:05d}.zip"
        await asyncio.to_thread(_write_part, target, bytes(content))
        content.clear()
        return target

    while True:
        query = select(UserActionEvent).where(
            UserActionEvent.occurred_at >= since, UserActionEvent.occurred_at < until
        )
        if last_time is not None:
            query = query.where(
                or_(
                    UserActionEvent.occurred_at > last_time,
                    and_(
                        UserActionEvent.occurred_at == last_time,
                        UserActionEvent.id > last_id,
                    ),
                )
            )
        query = query.order_by(UserActionEvent.occurred_at, UserActionEvent.id).limit(
            1000
        )
        async with db_manager.async_session() as session:
            rows = (await session.execute(query)).scalars().all()
        if not rows:
            break
        for event in rows:
            line = (
                json.dumps(
                    {
                        "id": event.id,
                        "occurred_at": event.occurred_at.isoformat(),
                        "user_id": event.user_id,
                        "chat_id": event.chat_id,
                        "message_id": event.message_id,
                        "event_name": event.event_name,
                        "surface": event.surface,
                        "outcome": event.outcome,
                        "subject_id": event.subject_id,
                        "task_id": event.task_id,
                        "details": event.details,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                + b"\n"
            )
            if content and len(content) + len(line) > MAX_EXPORT_PART_BYTES:
                yield await flush()
            content.extend(line)
            if len(content) >= MAX_EXPORT_PART_BYTES:
                yield await flush()
            last_time, last_id = event.occurred_at, event.id
    if content:
        yield await flush()


async def build_event_export(output_dir: Path, start: date, end: date) -> list[Path]:
    """Materialize parts for local tooling; delivery uses the iterator."""
    return [part async for part in iter_event_export(output_dir, start, end)]
