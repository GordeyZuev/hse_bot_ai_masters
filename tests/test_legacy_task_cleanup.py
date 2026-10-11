from importlib import import_module

import pytest

from src.core.database import db_manager
from src.core.sync.contracts import ParsedRows, SheetSnapshot, SyncReport
from src.core.sync.data_syncer import DataSyncer


sync_module = import_module("src.core.sync.data_syncer")


@pytest.mark.asyncio
@pytest.mark.parametrize("has_snapshot", [True, False])
async def test_legacy_cleanup_requires_all_valid_sheets(
    monkeypatch,
    has_snapshot,
) -> None:
    sender = DataSyncer()
    statements = []

    class Result:
        def __init__(self, values):
            self.values = values

        def scalars(self):
            return self

        def all(self):
            return self.values

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, statement):
            statements.append(statement)
            return Result([] if len(statements) == 1 else [42])

    async def noop(*_args, **_kwargs):
        return None

    async def subject_sync(*_args, **_kwargs):
        return {"success": True}

    async def deadline_snapshots():
        return [SheetSnapshot("1_Курс_Дедлайны", [])] if has_snapshot else []

    async def subject_snapshot(*_args):
        return SheetSnapshot("Дисциплины", [])

    async def apply_snapshot(*_args):
        return SyncReport(success=True), []

    monkeypatch.setattr(db_manager, "ensure_initialized", noop)
    monkeypatch.setattr(db_manager, "async_session", lambda: Session())
    monkeypatch.setattr(sender, "sync_subjects", subject_sync)
    monkeypatch.setattr(sender, "_apply_task_snapshot", apply_snapshot)
    monkeypatch.setattr(
        sync_module.sheets_manager, "get_deadline_snapshots", deadline_snapshots
    )
    monkeypatch.setattr(sync_module.sheets_manager, "get_snapshot", subject_snapshot)
    monkeypatch.setattr(sync_module, "parse_task_rows", lambda *_args: ParsedRows())
    monkeypatch.setattr(sync_module, "parse_subject_rows", lambda *_args: ParsedRows())

    result = await sender.sync_data(dry_run=True)

    assert result["deleted"] == (1 if has_snapshot else 0)
    assert len(statements) == (2 if has_snapshot else 1)
    if has_snapshot:
        assert "source_sheet IS NULL" in str(statements[1])
        assert "sheet_row_id IS NOT NULL" in str(statements[1])
