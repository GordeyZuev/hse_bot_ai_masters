"""Bounded, date-filtered exports of diagnostic logs for administrators."""

import json
import os
import re
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import BinaryIO
from zipfile import ZIP_DEFLATED, ZipFile


MAX_EXPORT_PART_BYTES = 8 * 1024 * 1024
_SOURCE_NAME = re.compile(
    r"^(?:app_(?:(?:jsonl|json)_)?(?:week_)?|errors_)[0-9]{4}-[0-9]{2}(?:-[0-9]{2})?.*\.(?:log|zip)$"
)


def log_sources(log_dir: Path, *, include_legacy: bool = False) -> list[Path]:
    if not log_dir.is_dir():
        return []
    return sorted(
        path
        for path in log_dir.iterdir()
        if path.is_file()
        and not path.is_symlink()
        and _SOURCE_NAME.match(path.name)
        and (include_legacy or not path.name.startswith("app_json_week_"))
    )


def cleanup_old_log_files(days_old: int = 30) -> int:
    """Remove old current and legacy logs that Loguru's retention cannot see."""
    cutoff = (datetime.now(UTC) - timedelta(days=days_old)).timestamp()
    log_dir = Path(os.getenv("LOG_DIR", "logs"))
    deleted = 0
    for path in log_sources(log_dir, include_legacy=True):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                deleted += 1
        except FileNotFoundError:
            continue
    return deleted


def _source_streams(path: Path) -> Iterator[tuple[str, BinaryIO]]:
    """Open one archive member at a time to bound file descriptors."""
    if path.suffix == ".zip":
        with ZipFile(path) as archive:
            for name in archive.namelist():
                if name.endswith(".log"):
                    with archive.open(name) as stream:
                        yield f"{path.name}/{name}", stream
    else:
        with path.open("rb") as stream:
            yield path.name, stream


def _line_date(line: bytes, source_name: str) -> str | None:
    if "jsonl" in source_name:
        try:
            return json.loads(line)["record"]["time"]["repr"][:10]
        except (ValueError, KeyError, TypeError):
            return None
    prefix = line[:10].decode("ascii", errors="ignore")
    return prefix if re.fullmatch(r"\d{4}-\d{2}-\d{2}", prefix) else None


def iter_log_export(
    log_dir: Path, output_dir: Path, start: date, end: date
) -> Iterator[Path]:
    """Yield each bounded ZIP as it is written, allowing immediate delivery."""
    export_number = 0
    start_day, end_day = start.isoformat(), end.isoformat()
    for source in log_sources(log_dir):
        for name, stream in _source_streams(source):
            part_number = 0
            content = bytearray()
            include_continuation = False
            is_jsonl = "jsonl" in name

            def flush(content: bytearray, name: str) -> Path:
                nonlocal part_number, export_number
                part_number += 1
                export_number += 1
                target = output_dir / f"logs-{export_number:05d}.zip"
                with ZipFile(target, "w", compression=ZIP_DEFLATED) as bundle:
                    source_name = Path(name)
                    bundle.writestr(
                        f"{source_name.stem}.part{part_number}{source_name.suffix}",
                        content,
                    )
                content.clear()
                return target

            for line in stream:
                line_day = _line_date(line, name)
                if is_jsonl:
                    include_continuation = (
                        line_day is not None and start_day <= line_day <= end_day
                    )
                elif line_day is not None:
                    include_continuation = start_day <= line_day <= end_day
                if not include_continuation:
                    continue
                if content and len(content) + len(line) > MAX_EXPORT_PART_BYTES:
                    yield flush(content, name)
                if len(line) > MAX_EXPORT_PART_BYTES:
                    for offset in range(0, len(line), MAX_EXPORT_PART_BYTES):
                        content.extend(line[offset : offset + MAX_EXPORT_PART_BYTES])
                        yield flush(content, name)
                else:
                    content.extend(line)
            if content:
                yield flush(content, name)


def build_log_export(
    log_dir: Path, output_dir: Path, start: date, end: date
) -> list[Path]:
    """Materialize parts for local tooling; delivery uses the iterator."""
    return list(iter_log_export(log_dir, output_dir, start, end))
