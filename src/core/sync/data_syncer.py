import asyncio
import os
import re
from datetime import datetime
from typing import Any

from dateutil import parser

from src.bot.services.notification_scheduler_service import (
    notification_scheduler_service,
)
from src.core.database import db_manager
from src.core.sync.gsheets_syncer import sheets_manager
from src.utils import get_logger
from src.utils.time import localize_naive_and_convert_to_utc


logger = get_logger()


class DataSyncer:
    def __init__(self):
        pass

    def parse_date(self, date_str: str) -> datetime | None:
        """Парсинг даты из различных форматов"""
        if not date_str or not date_str.strip():
            return None

        try:
            date_str = date_str.strip()
            parsed_date = parser.parse(date_str, dayfirst=True)

            # Устанавливаем время 23:59 если его нет
            if parsed_date.time() == datetime.min.time():
                parsed_date = parsed_date.replace(hour=23, minute=59)

            source_tz = os.getenv("TZ", "Europe/Moscow")
            return localize_naive_and_convert_to_utc(parsed_date, source_tz)
        except Exception as e:
            logger.warning(f"Не удалось распарсить дату '{date_str}': {e}")
            return None

    def extract_module_from_subject(self, subject_name: str) -> int:
        """Извлечение модуля из названия предмета"""
        module_match = re.search(r"(\d+)\s*модуль", subject_name, re.IGNORECASE)
        return int(module_match.group(1)) if module_match else 1

    def clean_subject_name(self, subject_name: str) -> str:
        """Очистка названия предмета от лишней информации"""
        cleaned = re.sub(r"\s*\d+\s*модуль\s*", "", subject_name, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", cleaned).strip()

    def extract_sheet_row_id(self, row_data: dict[str, Any]) -> int:
        """Извлечение ID строки из данных Google Sheets"""
        for field in ["ID", "id", "Row ID", "Номер строки", "№"]:
            if row_data.get(field):
                try:
                    return int(row_data[field])
                except (ValueError, TypeError):
                    continue

        # Используем хеш если ID не найден
        return abs(hash(str(sorted(row_data.items())))) % 1000000

    async def transform_sheets_data_to_db_format(
        self, sheets_data: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Преобразование данных из Google Sheets в формат базы данных"""
        await db_manager.ensure_initialized()
        transformed_data = []

        for row_data in sheets_data:
            try:
                subject_name_raw = row_data.get("Дисциплина", "").strip()
                hw_name = row_data.get("Название ДЗ", "").strip()

                if not subject_name_raw or not hw_name:
                    continue

                # Обработка предмета
                subject_name = self.clean_subject_name(subject_name_raw)

                async with db_manager.async_session() as session:
                    from sqlalchemy import select

                    from src.core.models import Subject
                    stmt = select(Subject).where(Subject.name == subject_name)
                    result = await session.execute(stmt)
                    subject = result.scalar_one_or_none()
                if not subject:
                    logger.warning(
                        f"Пропускаю дедлайн '{hw_name}' — предмет '{subject_name}' не найден. Сначала синхронизируйте 'Дисциплины'."
                    )
                    continue

                task_data = {
                    "subject_id": subject.id,
                    "hw_name": hw_name,
                    "source_link": row_data.get("Источник (Link)", "").strip() or None,
                    "soft_deadline_ts": self.parse_date(
                        row_data.get("Мягкий Дедлайн", "")
                    ),
                    "hard_deadline_ts": self.parse_date(
                        row_data.get("Жесткий Дедлайн", "")
                    ),
                    "note": row_data.get("Комментарий", "").strip() or "",
                    "sheet_row_id": self.extract_sheet_row_id(row_data),
                }

                transformed_data.append(task_data)

            except Exception as e:
                logger.error(f"Ошибка преобразования строки {row_data}: {e}")
                continue

        logger.info(f"Преобразовано: {len(transformed_data)}/{len(sheets_data)}")
        return transformed_data

    async def sync_data(self) -> dict[str, Any]:
        """Основная функция синхронизации данных."""
        try:
            logger.info("Начало синхронизации")
            await db_manager.ensure_initialized()

            # Получение и преобразование данных
            sheets_data = await sheets_manager.get_deadlines_data()
            if not sheets_data:
                logger.warning("Нет данных из Google Sheets")
                return {
                    "success": False,
                    "synced_count": 0,
                    "scheduled_notifications_count": 0,
                    "changes": [],
                }

            db_data = await self.transform_sheets_data_to_db_format(sheets_data)
            if not db_data:
                logger.warning("Нет данных для синхронизации")
                return {
                    "success": False,
                    "synced_count": 0,
                    "scheduled_notifications_count": 0,
                    "changes": [],
                }

            # Синхронизация
            synced_count = 0
            scheduled_notifications_count = 0
            current_sheet_row_ids = []
            changes: list[dict[str, Any]] = []

            for task_data in db_data:
                task, change_info = await db_manager.upsert_task(task_data)
                if task:
                    synced_count += 1
                    current_sheet_row_ids.append(task.sheet_row_id)

                    # Планируем уведомления и отправляем сообщение только если изменились дедлайны
                    if change_info.get("deadline_changed", False):
                        logger.info(f"sync_data: обнаружено изменение дедлайна {task.id} (soft={change_info.get('soft_deadline_changed', False)}, hard={change_info.get('hard_deadline_changed', False)})")
                        try:
                            notifications_count = await notification_scheduler_service.reschedule_notifications_for_updated_task(
                                task
                            )
                            scheduled_notifications_count += notifications_count
                            # Добавляем информацию об изменениях для отправки уведомлений
                            changes.append({
                                "deadline": task,
                                "change_info": change_info
                            })
                        except Exception as e:
                            logger.error(
                                f"Ошибка планирования уведомлений для дедлайна {task.id}: {e}"
                            )

            await db_manager.delete_outdated_tasks(current_sheet_row_ids)
            logger.info(
                f"Синхронизация: {synced_count} дедлайнов, {scheduled_notifications_count} увед."
            )
            return {
                "success": True,
                "synced_count": synced_count,
                "scheduled_notifications_count": scheduled_notifications_count,
                "changes": changes,
            }

        except Exception as e:
            logger.error(f"Ошибка синхронизации: {e}")
            return {
                "success": False,
                "synced_count": 0,
                "scheduled_notifications_count": 0,
                "changes": [],
            }

    async def sync_subjects(self) -> dict[str, int]:
        """Ручная синхронизация дисциплин из листа "Дисциплины".

        Правила:
        - Если есть sheet_subject_id, сначала ищем предмет только по ID (независимо от названия)
        - Если ID нет или предмет не найден по ID, ищем по (name, year)
        - Жесткая перезапись: name, is_active, ссылки, start/end модули; пустые ссылки затираются в NULL
        - Новые строки добавляем
        - Никаких планировщиков, вызывается вручную админом
        """
        try:
            await db_manager.ensure_initialized()
            subjects_rows = await sheets_manager.get_subjects_data()

            from sqlalchemy import and_, select

            from src.core.models import Subject

            updated, created = 0, 0

            async with db_manager.async_session() as session:
                for row in subjects_rows:
                    sheet_subject_id = row.get("sheet_subject_id")
                    name = row["name"]
                    year = row["year"]

                    subject = None

                    if sheet_subject_id is not None:
                        stmt = select(Subject).where(
                            Subject.sheet_subject_id == sheet_subject_id
                        )
                        result = await session.execute(stmt)
                        subject = result.scalar_one_or_none()

                    if subject is None:
                        stmt = select(Subject).where(
                            and_(Subject.name == name, Subject.year == year)
                        )
                        result = await session.execute(stmt)
                        subject = result.scalar_one_or_none()

                        # Защита: если нашли по названию, но ID отличается - обновляем ID
                        if (
                            subject
                            and sheet_subject_id is not None
                            and subject.sheet_subject_id != sheet_subject_id
                        ):
                            logger.warning(
                                f"Обнаружена рассинхронизация ID для предмета '{name}' (год {year}): "
                                f"в БД ID={subject.sheet_subject_id}, в таблице ID={sheet_subject_id}. "
                                f"Обновляю ID на значение из таблицы."
                            )

                    if subject:
                        incoming = {
                            "sheet_subject_id": sheet_subject_id,
                            "name": name,
                            "year": year,
                            "start_module": row.get("start_module"),
                            "end_module": row.get("end_module"),
                            "is_active": bool(row.get("is_active")),
                            "wiki_url": row.get("wiki_url") or None,
                            "vk_playlist_url": row.get("vk_playlist_url") or None,
                            "yt_playlist_url": row.get("yt_playlist_url") or None,
                        }

                        has_changes = False
                        for key, new_val in incoming.items():
                            if getattr(subject, key) != new_val:
                                setattr(subject, key, new_val)
                                has_changes = True

                        if has_changes:
                            session.add(subject)
                            updated += 1
                    else:
                        new_subject = Subject(
                            sheet_subject_id=sheet_subject_id,
                            name=name,
                            year=year,
                            start_module=row.get("start_module"),
                            end_module=row.get("end_module"),
                            is_active=bool(row.get("is_active")),
                            wiki_url=row.get("wiki_url"),
                            vk_playlist_url=row.get("vk_playlist_url"),
                            yt_playlist_url=row.get("yt_playlist_url"),
                        )
                        session.add(new_subject)
                        created += 1

                await session.commit()

            logger.info(f"Синхронизация дисциплин: обновлено={updated}, создано={created}")
            return {"updated": updated, "created": created}
        except Exception as e:
            logger.error(f"Ошибка синхронизации дисциплин: {e}")
            return {"updated": 0, "created": 0}


data_syncer = DataSyncer()


async def main():
    """Функция для тестирования синхронизации"""
    success = await data_syncer.sync_data()
    print("Синхронизация выполнена успешно!" if success else "Ошибка синхронизации")


if __name__ == "__main__":
    asyncio.run(main())
