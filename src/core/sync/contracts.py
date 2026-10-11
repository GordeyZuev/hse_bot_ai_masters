from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, Generic, TypeVar
from urllib.parse import urlparse


if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime


@dataclass(frozen=True, slots=True)
class RowError:
    sheet: str
    row_number: int
    row_id: int | None
    message: str


@dataclass(frozen=True, slots=True)
class SheetSnapshot:
    name: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True, slots=True)
class SubjectRow:
    sheet_subject_id: int
    name: str
    year: int | None
    modules: tuple[int, ...]
    leap_url: str | None
    youtube_url: str | None
    yandex_disk_url: str | None
    is_active: bool


@dataclass(frozen=True, slots=True)
class TaskRow:
    sheet_task_id: int
    source_sheet: str
    subject_name: str
    hw_name: str
    source_link: str | None
    soft_deadline_ts: datetime | None
    hard_deadline_ts: datetime | None
    note: str | None


T = TypeVar("T")


@dataclass(slots=True)
class ParsedRows(Generic[T]):
    values: list[T] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    seen_ids: set[int] = field(default_factory=set)
    fatal_error: str | None = None

    @property
    def ok(self) -> bool:
        return self.fatal_error is None


@dataclass(slots=True)
class SyncReport:
    success: bool = True
    fetched: int = 0
    valid: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    archived: int = 0
    deleted: int = 0
    reactivated: int = 0
    skipped: int = 0
    scheduled_notifications_count: int = 0
    errors: list[RowError] = field(default_factory=list)
    changes: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "fetched": self.fetched,
            "valid": self.valid,
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "archived": self.archived,
            "deleted": self.deleted,
            "reactivated": self.reactivated,
            "skipped": self.skipped,
            "synced_count": self.created + self.updated + self.unchanged,
            "scheduled_notifications_count": self.scheduled_notifications_count,
            "errors": [asdict(error) for error in self.errors],
            "changes": self.changes,
        }


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def normalize_url(value: Any) -> tuple[str | None, str | None]:
    if value is None or not str(value).strip():
        return None, None
    url = str(value).strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None, f"Некорректный URL: {url!r}"
    return url, None


def parse_modules(value: Any) -> tuple[tuple[int, ...], str | None]:
    if value is None or not str(value).strip():
        return (), None
    try:
        modules = tuple(
            sorted(
                {int(part.strip()) for part in str(value).split(",") if part.strip()}
            )
        )
    except ValueError:
        return (), f"Некорректный список модулей: {value!r}"
    if any(module < 1 or module > 8 for module in modules):
        return (), f"Модули должны быть в диапазоне 1-8: {value!r}"
    return modules, None


def parse_subject_rows(snapshot: SheetSnapshot) -> ParsedRows[SubjectRow]:
    result: ParsedRows[SubjectRow] = ParsedRows()
    seen_names: set[str] = set()
    if not snapshot.ok:
        result.fatal_error = snapshot.error
        return result

    required_headers = {"ID", "Дисциплина", "Active"}
    headers = (
        set().union(*(row.keys() for row in snapshot.rows)) if snapshot.rows else set()
    )
    missing = required_headers - headers
    if missing:
        result.fatal_error = f"Нет обязательных колонок: {', '.join(sorted(missing))}"
        return result

    for row_number, row in enumerate(snapshot.rows, start=2):
        name = str(row.get("Дисциплина") or "").strip()
        raw_id = row.get("ID")
        # Sheets commonly prefill hundreds of IDs in otherwise empty rows.
        if not name and not any(
            str(row.get(key) or "").strip()
            for key in ("Курс", "Модуль", "LEAP", "YouTube", "Ya Disk", "Active")
        ):
            continue
        row_id = _positive_int(raw_id)
        if row_id is not None:
            if row_id in result.seen_ids:
                result.fatal_error = f"Повторяющийся ID дисциплины: {row_id}"
                return result
            result.seen_ids.add(row_id)
        if row_id is None or not name:
            result.errors.append(
                RowError(snapshot.name, row_number, row_id, "Нужны ID и Дисциплина")
            )
            continue
        if name in seen_names:
            result.fatal_error = f"Название дисциплины должно быть уникальным для привязки дедлайнов: {name!r}"
            return result
        seen_names.add(name)
        year = _positive_int(row.get("Курс"))
        modules, modules_error = parse_modules(row.get("Модуль"))
        active_raw = str(row.get("Active") or "").strip().upper()
        is_active = active_raw == "TRUE"
        warnings = []
        if modules_error:
            warnings.append(modules_error)
        if active_raw not in {"", "TRUE", "FALSE"}:
            warnings.append(f"Некорректный Active {active_raw!r}")

        urls: dict[str, str | None] = {}
        for header, key in (
            ("LEAP", "leap_url"),
            ("YouTube", "youtube_url"),
            ("Ya Disk", "yandex_disk_url"),
        ):
            urls[key], url_error = normalize_url(row.get(header))
            if url_error:
                warnings.append(f"{header}: {url_error}")

        for warning in warnings:
            result.errors.append(RowError(snapshot.name, row_number, row_id, warning))

        # Invalid source values must never overwrite valid data with FALSE/NULL.
        if warnings:
            continue

        result.values.append(
            SubjectRow(
                sheet_subject_id=row_id,
                name=name,
                year=year,
                modules=modules,
                is_active=is_active,
                **urls,
            )
        )
    return result


def parse_task_rows(
    snapshot: SheetSnapshot,
    subject_names: set[str],
    parse_date: Callable[[str], datetime | None],
) -> ParsedRows[TaskRow]:
    result: ParsedRows[TaskRow] = ParsedRows()
    if not snapshot.ok:
        result.fatal_error = snapshot.error
        return result

    required_headers = {"ID", "Дисциплина", "Название ДЗ"}
    headers = (
        set().union(*(row.keys() for row in snapshot.rows)) if snapshot.rows else set()
    )
    missing = required_headers - headers
    if missing:
        result.fatal_error = f"Нет обязательных колонок: {', '.join(sorted(missing))}"
        return result

    for row_number, row in enumerate(snapshot.rows, start=2):
        raw_id = row.get("ID")
        subject_name = str(row.get("Дисциплина") or "").strip()
        hw_name = str(row.get("Название ДЗ") or "").strip()
        if (
            not subject_name
            and not hw_name
            and not any(
                str(row.get(key) or "").strip()
                for key in (
                    "Мягкий Дедлайн",
                    "Жесткий Дедлайн",
                    "Источник (Link)",
                    "Комментарий",
                )
            )
        ):
            continue
        row_id = _positive_int(raw_id)
        if row_id is not None:
            if row_id in result.seen_ids:
                result.fatal_error = f"Повторяющийся ID задания: {row_id}"
                return result
            result.seen_ids.add(row_id)
        if row_id is None or not subject_name or not hw_name:
            result.errors.append(
                RowError(
                    snapshot.name,
                    row_number,
                    row_id,
                    "Нужны ID, Дисциплина и Название ДЗ",
                )
            )
            continue
        if subject_name not in subject_names:
            result.errors.append(
                RowError(
                    snapshot.name,
                    row_number,
                    row_id,
                    f"Дисциплина {subject_name!r} отсутствует в справочнике",
                )
            )
            continue

        soft_raw = str(row.get("Мягкий Дедлайн") or "").strip()
        hard_raw = str(row.get("Жесткий Дедлайн") or "").strip()
        soft = parse_date(soft_raw) if soft_raw else None
        hard = parse_date(hard_raw) if hard_raw else None
        if (soft_raw and soft is None) or (hard_raw and hard is None):
            result.errors.append(
                RowError(snapshot.name, row_number, row_id, "Некорректная дата")
            )
            continue
        if soft is None and hard is None:
            result.errors.append(
                RowError(
                    snapshot.name,
                    row_number,
                    row_id,
                    "Нужен хотя бы один мягкий или жёсткий дедлайн",
                )
            )
            continue
        if soft and hard and soft > hard:
            result.errors.append(
                RowError(
                    snapshot.name,
                    row_number,
                    row_id,
                    "Мягкий дедлайн позже жёсткого",
                )
            )
            continue

        source_link, url_error = normalize_url(row.get("Источник (Link)"))
        if url_error:
            result.errors.append(RowError(snapshot.name, row_number, row_id, url_error))

        result.values.append(
            TaskRow(
                sheet_task_id=row_id,
                source_sheet=snapshot.name,
                subject_name=subject_name,
                hw_name=hw_name,
                source_link=source_link,
                soft_deadline_ts=soft,
                hard_deadline_ts=hard,
                note=str(row.get("Комментарий") or "").strip() or None,
            )
        )
    return result
