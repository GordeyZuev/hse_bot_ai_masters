import asyncio
import os
from dataclasses import asdict
from typing import Any

from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from gspread_asyncio import AsyncioGspreadClientManager

from src.core.sync.contracts import SheetSnapshot, parse_subject_rows
from src.utils import get_logger


load_dotenv("src/config/.env")
logger = get_logger()


class AsyncGoogleSheetsManager:
    SHEET_NAMES = ["1_Курс_Дедлайны", "2_Курс_Дедлайны"]
    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]

    def __init__(self):
        self.sheet_url = os.getenv("GOOGLE_SHEETS_URL")
        self.creds_file = os.getenv("GOOGLE_CREDS_FILE", "src/config/creds.json")
        self.client_manager = AsyncioGspreadClientManager(self.get_credentials)

    def get_credentials(self):
        """Получение учетных данных Google API"""
        try:
            creds = Credentials.from_service_account_file(self.creds_file)
            return creds.with_scopes(self.SCOPES)
        except Exception as e:
            logger.error(f"[SYSTEM] Ошибка загрузки учетных данных: {e}")
            raise

    async def get_sheet_data(self, sheet_name: str) -> list[dict[str, Any]]:
        """Асинхронное получение данных из листа"""
        try:
            if not self.sheet_url:
                raise ValueError("GOOGLE_SHEETS_URL не найден в переменных окружения")
            client = await self.client_manager.authorize()
            spreadsheet = await client.open_by_url(self.sheet_url)
            worksheet = await spreadsheet.worksheet(sheet_name)
            return await worksheet.get_all_records()
        except Exception as e:
            logger.error(f"[SYSTEM] Ошибка получения данных из '{sheet_name}': {e}")
            raise

    async def get_snapshot(self, sheet_name: str) -> SheetSnapshot:
        try:
            return SheetSnapshot(sheet_name, await self.get_sheet_data(sheet_name))
        except Exception as exc:
            return SheetSnapshot(sheet_name, error=str(exc))

    async def get_deadline_snapshots(self) -> list[SheetSnapshot]:
        return list(
            await asyncio.gather(
                *(self.get_snapshot(name) for name in self.SHEET_NAMES)
            )
        )

    async def get_deadlines_data(self) -> list[dict[str, Any]]:
        """Получение данных дедлайнов с нужных листов"""
        try:
            # Параллельное получение данных
            results = await self.get_deadline_snapshots()

            # Обработка результатов и фильтрация
            all_data = []
            for snapshot in results:
                if snapshot.ok:
                    filtered = [
                        item
                        for item in snapshot.rows
                        if item.get("Дисциплина") and item.get("Название ДЗ")
                    ]
                    all_data.extend(filtered)
                else:
                    logger.error(
                        f"[SYSTEM] Ошибка листа {snapshot.name}: {snapshot.error}"
                    )

            logger.info(f"[SYSTEM] Получено {len(all_data)} дедлайнов")
            return all_data

        except Exception as e:
            logger.exception(f"[SYSTEM] Ошибка получения дедлайнов: {e}")
            return []

    async def get_subjects_data(self) -> list[dict[str, Any]]:
        """Compatibility facade backed by the canonical subject contract."""
        parsed = parse_subject_rows(await self.get_snapshot("Дисциплины"))
        if not parsed.ok:
            raise ValueError(parsed.fatal_error or "Не удалось прочитать дисциплины")
        return [asdict(subject) for subject in parsed.values]


# Создаем экземпляр менеджера
sheets_manager = AsyncGoogleSheetsManager()


async def main():
    """Основная асинхронная функция"""
    return await sheets_manager.get_deadlines_data()


# Запуск
if __name__ == "__main__":
    try:
        deadlines = asyncio.run(main())
        logger.info(f"[SYSTEM] Получено записей: {len(deadlines)}")
        if deadlines:
            logger.info(f"Первая запись: {deadlines[0]}")
    except Exception as e:
        logger.critical(f"[SYSTEM] Критическая ошибка: {e}")
