import json
import os
import time
from datetime import date
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from aiogram.enums import ContentType

import src.bot.handlers.admin as admin_handlers
from src.bot.handlers.admin import _broadcast_types
from src.bot.services.log_export import build_log_export, cleanup_old_log_files


def test_broadcast_content_types_include_video() -> None:
    assert _broadcast_types[ContentType.VIDEO.value] == "Видео"
    assert _broadcast_types[ContentType.TEXT.value] == "Текст"


@pytest.mark.asyncio
async def test_events_button_is_inside_statistics(monkeypatch) -> None:
    async def statistics():
        return {}

    async def format_statistics(_stats):
        return "Статистика"

    monkeypatch.setattr(admin_handlers.admin_service, "get_bot_statistics", statistics)
    monkeypatch.setattr(admin_handlers, "format_statistics_message", format_statistics)
    monkeypatch.setattr(admin_handlers, "is_admin", lambda _user_id: True)

    markup = []

    class Message:
        async def answer(self, _text, *, reply_markup):
            markup.append(reply_markup)

    await admin_handlers.show_statistics(Message(), SimpleNamespace(tg_user_id=42))
    stats_buttons = [
        button.callback_data for row in markup[-1].inline_keyboard for button in row
    ]
    assert "admin_events" in stats_buttons

    async def callback_answer(*_args, **_kwargs):
        return None

    async def capture_panel(_message, _text, *, reply_markup):
        markup.append(reply_markup)

    monkeypatch.setattr(admin_handlers, "safe_edit_message", capture_panel)
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        answer=callback_answer,
        message=Message(),
    )
    await admin_handlers.callback_admin_panel(callback, SimpleNamespace(tg_user_id=42))
    panel_buttons = [
        button.callback_data for row in markup[-1].inline_keyboard for button in row
    ]
    assert "admin_stats" in panel_buttons
    assert "admin_events" not in panel_buttons


def test_log_export_filters_dates_and_contains_both_logs(tmp_path) -> None:
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    source_dir.mkdir()
    output_dir.mkdir()
    (source_dir / "app_week_2026-09-28.log").write_bytes(
        b"2026-09-28 old line\n2026-10-10 new line\ntraceback continuation\n"
    )
    (source_dir / "errors_2026-10.log").write_bytes(b"2026-10-10 error line\n")
    (source_dir / "app_jsonl_2026-10-10.log").write_text(
        json.dumps({"record": {"time": {"repr": "2026-10-10T12:00:00+03:00"}}}) + "\n"
    )

    parts = build_log_export(
        source_dir, output_dir, date(2026, 10, 10), date(2026, 10, 10)
    )
    assert len(parts) == 3
    contents = []
    for part in parts:
        with ZipFile(part) as archive:
            contents.extend(archive.read(name) for name in archive.namelist())
    assert any(b"new line" in content for content in contents)
    assert any(b"error line" in content for content in contents)
    assert any(b"traceback continuation" in content for content in contents)
    assert any(b"record" in content for content in contents)
    assert all(b"old line" not in content for content in contents)


def test_log_export_splits_big_source(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("src.bot.services.log_export.MAX_EXPORT_PART_BYTES", 100)
    source = tmp_path / "app_2026-10-10.log"
    source.write_bytes(b"2026-10-10 12:00:00 current\n" * 20)
    output = tmp_path / "out"
    output.mkdir()

    parts = build_log_export(tmp_path, output, date(2026, 10, 10), date(2026, 10, 10))

    assert len(parts) > 1
    recovered = bytearray()
    for part in parts:
        with ZipFile(part) as archive:
            payload = archive.read(archive.namelist()[0])
            assert len(payload) <= 100
            recovered.extend(payload)
    assert recovered == source.read_bytes()


def test_log_export_reads_rotated_zip(tmp_path) -> None:
    source = tmp_path / "app_2026-10-10.2026-10-10_12-00-00.log.zip"
    with ZipFile(source, "w") as archive:
        archive.writestr(
            "app_2026-10-10.2026-10-10_12-00-00.log", "2026-10-10 12:00:00 archived\n"
        )
    output = tmp_path / "out"
    output.mkdir()

    parts = build_log_export(tmp_path, output, date(2026, 10, 10), date(2026, 10, 10))

    assert len(parts) == 1
    with ZipFile(parts[0]) as archive:
        assert b"archived" in archive.read(archive.namelist()[0])


def test_log_export_skips_invalid_jsonl_lines(tmp_path) -> None:
    source = tmp_path / "app_jsonl_2026-10-10.log"
    source.write_text(
        json.dumps({"record": {"time": {"repr": "2026-10-10T12:00:00+00:00"}}})
        + "\n"
        + "broken json\n"
        + json.dumps({"record": {"time": {"repr": "2026-10-11T12:00:00+00:00"}}})
        + "\n"
    )
    output = tmp_path / "out"
    output.mkdir()

    parts = build_log_export(tmp_path, output, date(2026, 10, 10), date(2026, 10, 10))

    assert len(parts) == 1
    with ZipFile(parts[0]) as archive:
        lines = archive.read(archive.namelist()[0]).splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["record"]["time"]["repr"].startswith("2026-10-10")


def test_cleanup_removes_old_legacy_logs_only(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    old = tmp_path / "app_json_week_2026-02-09.log"
    old.write_text("legacy")
    os.utime(old, (time.time() - 40 * 86400, time.time() - 40 * 86400))
    recent = tmp_path / "app_2026-10-11.log"
    recent.write_text("current")
    unrelated = tmp_path / "backup.log"
    unrelated.write_text("preserve")

    assert cleanup_old_log_files(days_old=30) == 1
    assert not old.exists()
    assert recent.exists()
    assert unrelated.exists()
