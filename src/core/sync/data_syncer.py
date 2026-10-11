from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from dateutil import parser
from sqlalchemy import delete, select, update

from src.bot.services.notification_scheduler_service import (
    notification_scheduler_service,
)
from src.core.database import db_manager
from src.core.models import (
    ChatScheduledNotification,
    ScheduledNotification,
    Subject,
    Task,
)
from src.core.sync.contracts import (
    ParsedRows,
    RowError,
    SubjectRow,
    SyncReport,
    TaskRow,
    parse_subject_rows,
    parse_task_rows,
)
from src.core.sync.gsheets_syncer import sheets_manager
from src.utils import get_logger
from src.utils.time import localize_naive_and_convert_to_utc, utc_now


logger = get_logger()


class DataSyncer:
    @staticmethod
    def _match_subject_rows(
        rows: list[SubjectRow], existing: list[Subject]
    ) -> list[tuple[SubjectRow, Subject | None]]:
        by_sheet_id = {
            subject.sheet_subject_id: subject
            for subject in existing
            if subject.sheet_subject_id is not None
        }
        by_identity: dict[tuple[str, int | None], list[Subject]] = {}
        for subject in existing:
            by_identity.setdefault((subject.name, subject.year), []).append(subject)

        incoming_identities = {(row.name, row.year) for row in rows}
        matched: set[int] = set()
        planned: list[tuple[SubjectRow, Subject | None]] = []
        for row in rows:
            identity_matches = by_identity.get((row.name, row.year), [])
            if len(identity_matches) > 1:
                raise ValueError(f"Неоднозначная дисциплина в БД: {row.name!r}")
            subject = identity_matches[0] if identity_matches else None
            if subject is None:
                candidate = by_sheet_id.get(row.sheet_subject_id)
                if (
                    candidate is not None
                    and candidate.id not in matched
                    and (candidate.name, candidate.year) not in incoming_identities
                ):
                    subject = candidate
            if subject is not None:
                matched.add(subject.id)
            planned.append((row, subject))
        return planned

    def parse_date(self, date_str: str) -> datetime | None:
        """Parse a sheet date in the configured academic timezone."""
        if not date_str or not date_str.strip():
            return None
        try:
            parsed_date = parser.parse(date_str.strip(), dayfirst=True)
            if parsed_date.time() == datetime.min.time():
                parsed_date = parsed_date.replace(hour=23, minute=59)
            return localize_naive_and_convert_to_utc(
                parsed_date, os.getenv("TZ", "Europe/Moscow")
            )
        except Exception as exc:
            logger.warning(f"Не удалось распарсить дату {date_str!r}: {exc}")
            return None

    @staticmethod
    def _subject_values(row: SubjectRow) -> dict[str, Any]:
        return {
            "sheet_subject_id": row.sheet_subject_id,
            "name": row.name,
            "year": row.year,
            "modules": list(row.modules),
            "leap_url": row.leap_url,
            "youtube_url": row.youtube_url,
            "yandex_disk_url": row.yandex_disk_url,
            "is_active": row.is_active,
            "is_archived": False,
            "archived_at": None,
        }

    async def sync_subjects(self, dry_run: bool = False) -> dict[str, Any]:
        await db_manager.ensure_initialized()
        snapshot = await sheets_manager.get_snapshot("Дисциплины")
        parsed = parse_subject_rows(snapshot)
        valid_ids = {row.sheet_subject_id for row in parsed.values}
        report = SyncReport(
            success=parsed.ok,
            fetched=len(snapshot.rows),
            valid=len(parsed.values),
            skipped=len(parsed.seen_ids - valid_ids)
            + sum(error.row_id is None for error in parsed.errors),
            errors=list(parsed.errors),
        )
        if not parsed.ok:
            report.errors.append(
                RowError(snapshot.name, 1, None, parsed.fatal_error or "Ошибка листа")
            )
            logger.error(f"[SYSTEM] Дисциплины не применены: {parsed.fatal_error}")
            return report.as_dict()

        now = utc_now()
        activated_subject_ids: set[int] = set()
        deactivated_subject_ids: set[int] = set()
        async with db_manager.async_session() as session:
            existing = list((await session.execute(select(Subject))).scalars().all())
            originally_managed = {
                subject.id
                for subject in existing
                if subject.sheet_subject_id is not None
            }
            original_sheet_ids = {
                subject.id: subject.sheet_subject_id for subject in existing
            }

            try:
                planned = self._match_subject_rows(parsed.values, existing)
            except ValueError as exc:
                report.success = False
                report.errors.append(RowError(snapshot.name, 1, None, str(exc)))
                return report.as_dict()
            matched = {subject.id for _row, subject in planned if subject is not None}
            by_sheet_id = {
                subject.sheet_subject_id: subject
                for subject in existing
                if subject.sheet_subject_id is not None
            }

            # A reordered sheet may swap IDs. Release the old unique sheet IDs
            # before assigning new ones; subject PKs and all user links stay put.
            remapped = any(
                subject is not None and subject.sheet_subject_id != row.sheet_subject_id
                for row, subject in planned
            ) or any(
                subject is None and row.sheet_subject_id in by_sheet_id
                for row, subject in planned
            )
            if remapped and not dry_run:
                for subject in existing:
                    if subject.sheet_subject_id is not None:
                        subject.sheet_subject_id = None
                await session.flush()

            for row, subject in planned:
                values = self._subject_values(row)
                if subject is None:
                    report.created += 1
                    if not dry_run:
                        session.add(Subject(**values, last_synced_at=now))
                    continue

                was_archived = bool(subject.is_archived)
                was_effective = bool(subject.is_active and not subject.is_archived)
                will_be_effective = row.is_active
                changed = original_sheet_ids[subject.id] != row.sheet_subject_id or any(
                    key != "sheet_subject_id" and getattr(subject, key) != value
                    for key, value in values.items()
                )
                if subject.id is not None:
                    if not was_effective and will_be_effective:
                        activated_subject_ids.add(subject.id)
                    elif was_effective and not will_be_effective:
                        deactivated_subject_ids.add(subject.id)
                if was_archived:
                    report.reactivated += 1
                if changed:
                    report.updated += 1
                else:
                    report.unchanged += 1
                if not dry_run:
                    for key, value in values.items():
                        setattr(subject, key, value)
                    subject.yt_playlist_url = row.youtube_url
                    subject.last_synced_at = now

            for subject in existing:
                if (
                    subject.id in originally_managed
                    and subject.id not in matched
                    and not subject.is_archived
                    and not parsed.errors
                ):
                    report.archived += 1
                    if not dry_run:
                        if subject.id is not None:
                            deactivated_subject_ids.add(subject.id)
                        subject.is_archived = True
                        subject.archived_at = now
                        subject.is_active = False

            if not dry_run and deactivated_subject_ids:
                task_ids = list(
                    (
                        await session.execute(
                            select(Task.id).where(
                                Task.subject_id.in_(deactivated_subject_ids)
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                if task_ids:
                    for notification_model in (
                        ScheduledNotification,
                        ChatScheduledNotification,
                    ):
                        await session.execute(
                            update(notification_model)
                            .where(
                                notification_model.deadline_id.in_(task_ids),
                                notification_model.status.in_(
                                    ["scheduled", "processing", "retry"]
                                ),
                            )
                            .values(status="cancelled", updated_at=now)
                        )

            if dry_run:
                await session.rollback()
            else:
                await session.commit()

        logger.info(
            "[SYSTEM] Дисциплины: "
            f"created={report.created}, updated={report.updated}, "
            f"archived={report.archived}, errors={len(report.errors)}"
        )
        result = report.as_dict()
        result["activated_subject_ids"] = sorted(activated_subject_ids)
        result["deactivated_subject_ids"] = sorted(deactivated_subject_ids)
        return result

    @staticmethod
    def _task_values(row: TaskRow, subject_id: int) -> dict[str, Any]:
        return {
            "subject_id": subject_id,
            "hw_name": row.hw_name,
            "source_link": row.source_link,
            "soft_deadline_ts": row.soft_deadline_ts,
            "hard_deadline_ts": row.hard_deadline_ts,
            "note": row.note,
            "sheet_row_id": row.sheet_task_id,
            "source_sheet": row.source_sheet,
            "is_archived": False,
            "archived_at": None,
        }

    async def _apply_task_snapshot(
        self,
        parsed: ParsedRows[TaskRow],
        sheet_name: str,
        dry_run: bool,
        all_seen: set[int],
        allow_delete: bool,
    ) -> tuple[SyncReport, list[tuple[Task, dict[str, Any]]]]:
        valid_ids = {row.sheet_task_id for row in parsed.values}
        report = SyncReport(
            success=parsed.ok,
            valid=len(parsed.values),
            skipped=len(parsed.seen_ids - valid_ids)
            + sum(error.row_id is None for error in parsed.errors),
            errors=list(parsed.errors),
        )
        changed_tasks: list[tuple[Task, dict[str, Any]]] = []
        now = utc_now()

        async with db_manager.async_session() as session:
            subjects = list((await session.execute(select(Subject))).scalars().all())
            subjects_by_name = {subject.name: subject for subject in subjects}
            all_tasks = list((await session.execute(select(Task))).scalars().all())
            by_sheet_id = {
                task.sheet_row_id: task
                for task in all_tasks
                if task.sheet_row_id is not None
            }

            for row in parsed.values:
                subject = subjects_by_name.get(row.subject_name)
                if subject is None and not dry_run:
                    report.errors.append(
                        RowError(
                            sheet_name,
                            0,
                            row.sheet_task_id,
                            f"Дисциплина {row.subject_name!r} не найдена после sync",
                        )
                    )
                    report.skipped += 1
                    continue
                subject_id = subject.id if subject is not None else 0
                values = self._task_values(row, subject_id)
                task = by_sheet_id.get(row.sheet_task_id)
                if task is None:
                    report.created += 1
                    if not dry_run:
                        task = Task(
                            **values,
                            created_at=now,
                            updated_at=now,
                            last_synced_at=now,
                        )
                        session.add(task)
                        await session.flush()
                        changed_tasks.append(
                            (task, {"is_new": True, "deadline_changed": True})
                        )
                    continue

                old_soft = task.soft_deadline_ts
                old_hard = task.hard_deadline_ts
                was_archived = bool(task.is_archived)
                changed = any(
                    getattr(task, key) != value for key, value in values.items()
                )
                deadline_changed = (
                    old_soft != row.soft_deadline_ts
                    or old_hard != row.hard_deadline_ts
                    or was_archived
                )
                if was_archived:
                    report.reactivated += 1
                if changed:
                    report.updated += 1
                else:
                    report.unchanged += 1
                if not dry_run:
                    for key, value in values.items():
                        setattr(task, key, value)
                    task.updated_at = now
                    task.last_synced_at = now
                    if deadline_changed:
                        changed_tasks.append(
                            (
                                task,
                                {
                                    "is_new": False,
                                    "deadline_changed": True,
                                    "soft_deadline_changed": old_soft
                                    != row.soft_deadline_ts,
                                    "hard_deadline_changed": old_hard
                                    != row.hard_deadline_ts,
                                    "old_soft_deadline_ts": old_soft,
                                    "old_hard_deadline_ts": old_hard,
                                },
                            )
                        )

            to_delete = [
                task
                for task in all_tasks
                if task.source_sheet == sheet_name and task.sheet_row_id not in all_seen
            ]
            # An invalid row can hide a task ID; never delete from a partial sheet.
            if parsed.errors or not allow_delete:
                to_delete = []
            report.deleted = len(to_delete)
            if not dry_run and to_delete:
                await session.execute(
                    delete(Task).where(Task.id.in_([task.id for task in to_delete]))
                )

            if dry_run:
                await session.rollback()
            else:
                await session.commit()
        return report, changed_tasks

    async def sync_data(self, dry_run: bool = False) -> dict[str, Any]:
        """Synchronize subjects and task sheets without cross-sheet data loss."""
        await db_manager.ensure_initialized()
        subject_report = await self.sync_subjects(dry_run=dry_run)
        if not subject_report.get("success"):
            return subject_report

        snapshots = await sheets_manager.get_deadline_snapshots()
        async with db_manager.async_session() as session:
            subjects = list((await session.execute(select(Subject))).scalars().all())
        subject_names = {subject.name for subject in subjects}
        if dry_run:
            dry_subjects = parse_subject_rows(
                await sheets_manager.get_snapshot("Дисциплины")
            )
            subject_names.update(row.name for row in dry_subjects.values)

        parsed_by_sheet: dict[str, ParsedRows[TaskRow]] = {}
        for snapshot in snapshots:
            parsed_by_sheet[snapshot.name] = parse_task_rows(
                snapshot, subject_names, self.parse_date
            )

        successful = [parsed for parsed in parsed_by_sheet.values() if parsed.ok]
        all_seen: set[int] = set()
        duplicate_ids: set[int] = set()
        for parsed in successful:
            duplicate_ids |= all_seen & parsed.seen_ids
            all_seen |= parsed.seen_ids
        if duplicate_ids:
            message = (
                f"ID заданий встречаются в нескольких листах: {sorted(duplicate_ids)}"
            )
            return SyncReport(
                success=False,
                errors=[RowError("Дедлайны", 1, None, message)],
            ).as_dict()

        total = SyncReport(success=bool(successful))
        total.fetched = sum(len(snapshot.rows) for snapshot in snapshots)
        changes: list[tuple[Task, dict[str, Any]]] = []
        for snapshot in snapshots:
            parsed = parsed_by_sheet[snapshot.name]
            if not parsed.ok:
                total.success = False
                total.errors.append(
                    RowError(
                        snapshot.name,
                        1,
                        None,
                        parsed.fatal_error or "Ошибка чтения листа",
                    )
                )
                continue
            report, sheet_changes = await self._apply_task_snapshot(
                parsed,
                snapshot.name,
                dry_run,
                all_seen,
                len(successful) == len(snapshots),
            )
            for field in (
                "valid",
                "created",
                "updated",
                "unchanged",
                "archived",
                "deleted",
                "reactivated",
                "skipped",
            ):
                setattr(total, field, getattr(total, field) + getattr(report, field))
            total.errors.extend(report.errors)
            changes.extend(sheet_changes)

        # IDs are globally unique across all task sheets. Once every sheet has
        # been read without row errors, a legacy task absent from all of them
        # is genuinely removed; tasks still present got source_sheet above.
        if successful and len(successful) == len(snapshots) and not total.errors:
            async with db_manager.async_session() as session:
                legacy_ids = list(
                    (
                        await session.execute(
                            select(Task.id).where(
                                Task.source_sheet.is_(None),
                                Task.sheet_row_id.is_not(None),
                                Task.sheet_row_id.not_in(all_seen),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                total.deleted += len(legacy_ids)
                if not dry_run and legacy_ids:
                    await session.execute(delete(Task).where(Task.id.in_(legacy_ids)))
                    await session.commit()

        if not dry_run:
            async with db_manager.async_session() as session:
                active_subject_ids = set(
                    (
                        await session.execute(
                            select(Subject.id).where(
                                Subject.is_active,
                                Subject.is_archived.is_(False),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            changed_task_ids = {task.id for task, _change_info in changes}
            activated_subject_ids = subject_report.get("activated_subject_ids", [])
            if activated_subject_ids:
                async with db_manager.async_session() as session:
                    reactivated_tasks = list(
                        (
                            await session.execute(
                                select(Task).where(
                                    Task.subject_id.in_(activated_subject_ids),
                                    Task.is_archived.is_(False),
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                changes.extend(
                    (task, {"deadline_changed": False, "subject_activated": True})
                    for task in reactivated_tasks
                    if task.id not in changed_task_ids
                )

            for task, change_info in changes:
                try:
                    count = await notification_scheduler_service.reschedule_notifications_for_updated_task(
                        task
                    )
                    total.scheduled_notifications_count += count
                    if task.subject_id in active_subject_ids and change_info.get(
                        "deadline_changed"
                    ):
                        total.changes.append(
                            {"deadline": task, "change_info": change_info}
                        )
                except Exception as exc:
                    total.errors.append(
                        RowError(
                            task.source_sheet or "Дедлайны",
                            0,
                            task.sheet_row_id,
                            f"Не удалось перепланировать уведомления: {exc}",
                        )
                    )

        logger.info(
            "[SYSTEM] Дедлайны: "
            f"created={total.created}, updated={total.updated}, "
            f"deleted={total.deleted}, errors={len(total.errors)}"
        )
        return total.as_dict()


data_syncer = DataSyncer()
