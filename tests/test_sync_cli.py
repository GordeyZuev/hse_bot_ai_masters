import sys
from pathlib import Path

import pytest

import main as cli_module


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("errors", "exit_code"),
    [
        ([], 0),
        (
            [
                {
                    "sheet": "Дедлайны",
                    "row_number": 7,
                    "row_id": 4,
                    "message": "Некорректная дата",
                }
            ],
            1,
        ),
    ],
)
async def test_sync_dry_run_fails_when_sheet_has_row_errors(
    monkeypatch, errors, exit_code
) -> None:
    class FakeDatabase:
        async def ensure_initialized(self):
            return None

    class FakeApp:
        db_manager = FakeDatabase()

        async def run_single_sync(self, *, dry_run):
            assert dry_run is True
            return {"success": True, "errors": errors}

    monkeypatch.setattr(cli_module, "HSEBotSyncApp", FakeApp)
    monkeypatch.setattr(sys, "argv", ["main.py", "sync", "--dry-run"])
    assert cli_module.main.__globals__["HSEBotSyncApp"] is FakeApp
    assert (
        Path(cli_module.__file__).resolve()
        == Path(__file__).resolve().parents[1] / "main.py"
    )

    with pytest.raises(SystemExit) as exc:
        await cli_module.main()
    assert exc.value.code == exit_code
