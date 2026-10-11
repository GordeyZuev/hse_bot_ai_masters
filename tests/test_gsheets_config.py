import pytest

from src.core.sync.gsheets_syncer import AsyncGoogleSheetsManager


@pytest.mark.asyncio
async def test_missing_sheet_url_fails_on_read_not_import(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_SHEETS_URL", raising=False)

    manager = AsyncGoogleSheetsManager()
    snapshot = await manager.get_snapshot("Дисциплины")

    assert not snapshot.ok
    assert "GOOGLE_SHEETS_URL" in (snapshot.error or "")
