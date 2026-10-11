from datetime import UTC, datetime

from src.core.models import Subject
from src.core.sync.contracts import (
    SheetSnapshot,
    SubjectRow,
    parse_subject_rows,
    parse_task_rows,
)
from src.core.sync.data_syncer import DataSyncer


def _parse_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%d.%m.%y %H:%M").replace(tzinfo=UTC)
    except ValueError:
        return None


def test_subject_contract_keeps_sparse_modules_and_recording_links() -> None:
    parsed = parse_subject_rows(
        SheetSnapshot(
            "Дисциплины",
            [
                {
                    "ID": 3,
                    "Дисциплина": "Инструменты разработки PRO",
                    "Курс": 1,
                    "Модуль": "1, 3, 3",
                    "LEAP": "https://example.com/leap",
                    "YouTube": "",
                    "Ya Disk": "https://disk.yandex.ru/example",
                    "Active": "TRUE",
                }
            ],
        )
    )

    assert parsed.ok
    assert parsed.values[0].modules == (1, 3)
    assert parsed.values[0].leap_url == "https://example.com/leap"
    assert parsed.values[0].youtube_url is None
    assert parsed.values[0].yandex_disk_url == "https://disk.yandex.ru/example"
    assert parsed.values[0].is_active is True


def test_incomplete_subject_is_imported_inactive() -> None:
    parsed = parse_subject_rows(
        SheetSnapshot(
            "Дисциплины",
            [{"ID": 14, "Дисциплина": "Глубинное обучение", "Курс": "", "Active": ""}],
        )
    )

    assert parsed.ok
    assert parsed.values[0].year is None
    assert parsed.values[0].modules == ()
    assert parsed.values[0].is_active is False


def test_invalid_subject_fields_never_overwrite_existing_values() -> None:
    parsed = parse_subject_rows(
        SheetSnapshot(
            "Дисциплины",
            [
                {"ID": 1, "Дисциплина": "SQL", "Active": "TRUЕ"},
                {"ID": 2, "Дисциплина": "ML", "Active": "TRUE", "Модуль": "abc"},
                {
                    "ID": 3,
                    "Дисциплина": "Python",
                    "Active": "TRUE",
                    "LEAP": "not-a-url",
                },
            ],
        )
    )
    assert parsed.values == []
    assert len(parsed.errors) == 3
    assert parsed.seen_ids == {1, 2, 3}


def test_missing_active_column_fails_subject_sync() -> None:
    parsed = parse_subject_rows(
        SheetSnapshot("Дисциплины", [{"ID": 1, "Дисциплина": "SQL"}])
    )
    assert not parsed.ok
    assert "Active" in (parsed.fatal_error or "")


def test_duplicate_subject_name_is_fatal_because_tasks_have_no_subject_id() -> None:
    parsed = parse_subject_rows(
        SheetSnapshot(
            "Дисциплины",
            [
                {"ID": 1, "Дисциплина": "SQL", "Active": "TRUE"},
                {"ID": 2, "Дисциплина": "SQL", "Active": "TRUE"},
            ],
        )
    )

    assert not parsed.ok
    assert "уникальным" in (parsed.fatal_error or "")


def test_task_requires_title_subject_and_at_least_one_deadline() -> None:
    parsed = parse_task_rows(
        SheetSnapshot(
            "1_Курс_Дедлайны",
            [
                {
                    "ID": 1001,
                    "Дисциплина": "SQL",
                    "Название ДЗ": "HW_1",
                    "Мягкий Дедлайн": "",
                    "Жесткий Дедлайн": "",
                }
            ],
        ),
        {"SQL"},
        _parse_date,
    )

    assert parsed.values == []
    assert "хотя бы один" in parsed.errors[0].message
    assert parsed.seen_ids == {1001}


def test_task_allows_soft_and_hard_deadlines() -> None:
    parsed = parse_task_rows(
        SheetSnapshot(
            "1_Курс_Дедлайны",
            [
                {
                    "ID": 1001,
                    "Дисциплина": "SQL",
                    "Название ДЗ": "HW_1",
                    "Мягкий Дедлайн": "13.09.26 23:59",
                    "Жесткий Дедлайн": "10.10.26 23:59",
                }
            ],
        ),
        {"SQL"},
        _parse_date,
    )

    assert parsed.ok
    assert len(parsed.values) == 1
    assert parsed.values[0].soft_deadline_ts is not None
    assert parsed.values[0].hard_deadline_ts is not None


def test_task_subject_must_match_catalog_exactly() -> None:
    parsed = parse_task_rows(
        SheetSnapshot(
            "1_Курс_Дедлайны",
            [
                {
                    "ID": 1001,
                    "Дисциплина": "SQL",
                    "Название ДЗ": "HW_1",
                    "Жесткий Дедлайн": "10.10.26 23:59",
                }
            ],
        ),
        {"Python для анализа данных & SQL"},
        _parse_date,
    )

    assert parsed.values == []
    assert "отсутствует" in parsed.errors[0].message


def test_task_rejects_soft_deadline_after_hard_deadline() -> None:
    parsed = parse_task_rows(
        SheetSnapshot(
            "1_Курс_Дедлайны",
            [
                {
                    "ID": 1001,
                    "Дисциплина": "SQL",
                    "Название ДЗ": "HW_1",
                    "Мягкий Дедлайн": "11.10.26 23:59",
                    "Жесткий Дедлайн": "10.10.26 23:59",
                }
            ],
        ),
        {"SQL"},
        _parse_date,
    )

    assert parsed.values == []
    assert "позже" in parsed.errors[0].message


def test_prefilled_ids_without_content_are_placeholders() -> None:
    subjects = parse_subject_rows(
        SheetSnapshot(
            "Дисциплины",
            [
                {"ID": 1, "Дисциплина": "SQL", "Active": "TRUE"},
                {"ID": 2, "Дисциплина": "", "Active": ""},
            ],
        )
    )
    tasks = parse_task_rows(
        SheetSnapshot(
            "1_Курс_Дедлайны",
            [
                {
                    "ID": 1001,
                    "Дисциплина": "SQL",
                    "Название ДЗ": "HW",
                    "Жесткий Дедлайн": "10.10.26 23:59",
                },
                {"ID": 1002, "Дисциплина": "", "Название ДЗ": ""},
            ],
        ),
        {"SQL"},
        _parse_date,
    )

    assert subjects.errors == []
    assert subjects.seen_ids == {1}
    assert tasks.errors == []
    assert tasks.seen_ids == {1001}


def test_subject_id_reordering_matches_stable_name_and_year() -> None:
    old_a = Subject(id=11, sheet_subject_id=1, name="SQL", year=1)
    old_b = Subject(id=22, sheet_subject_id=2, name="ML", year=2)
    rows = [
        SubjectRow(2, "SQL", 1, (), None, None, None, True),
        SubjectRow(1, "ML", 2, (), None, None, None, True),
    ]

    planned = DataSyncer._match_subject_rows(rows, [old_a, old_b])

    assert [subject.id for _row, subject in planned] == [11, 22]
