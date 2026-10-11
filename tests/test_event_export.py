import json
from datetime import UTC, date, datetime
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

import src.bot.services.event_export as export_module


@pytest.mark.asyncio
async def test_event_export_streams_complete_jsonl_in_parts(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(export_module, "MAX_EXPORT_PART_BYTES", 250)
    rows = [
        SimpleNamespace(
            id=index,
            occurred_at=datetime(2026, 10, 10, 12, 0, tzinfo=UTC),
            user_id=42,
            chat_id=17,
            message_id=index,
            event_name="button_clicked",
            surface="private",
            outcome="handled",
            subject_id=None,
            task_id=None,
            details={"callback_data": f"button_{index}"},
        )
        for index in range(5)
    ]

    calls = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, _query):
            calls.append(True)
            batch = rows if len(calls) == 1 else []
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: batch))

    monkeypatch.setattr(export_module.db_manager, "async_session", FakeSession)

    parts = await export_module.build_event_export(
        tmp_path, date(2026, 10, 10), date(2026, 10, 10)
    )

    assert len(parts) > 1
    exported = []
    for part in parts:
        with ZipFile(part) as archive:
            content = archive.read(archive.namelist()[0])
            assert len(content) <= 250
            exported.extend(json.loads(line) for line in content.splitlines())
    assert [item["id"] for item in exported] == list(range(5))
    assert exported[0]["details"] == {"callback_data": "button_0"}
