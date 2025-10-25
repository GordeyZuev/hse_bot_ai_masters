import asyncio
import os
from typing import Any

from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from gspread_asyncio import AsyncioGspreadClientManager

from src.utils import get_logger


load_dotenv("src/config/.env")
logger = get_logger()


class AsyncGoogleSheetsManager:
    SHEET_NAMES = ["1_Курс_Дедлайны", "2_Курс_Дедлайны"]
    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    def __init__(self):
        self.sheet_url = os.getenv("GOOGLE_SHEETS_URL")
        if not self.sheet_url:
            raise ValueError("GOOGLE_SHEETS_URL не найден в переменных окружения")

        self.creds_file = os.getenv("GOOGLE_CREDS_FILE", "src/config/creds.json")
        self.client_manager = AsyncioGspreadClientManager(self.get_credentials)

    def get_credentials(self):
        """Получение учетных данных Google API"""
        try:
            creds = Credentials.from_service_account_file(self.creds_file)
            return creds.with_scopes(self.SCOPES)
        except Exception as e:
            logger.error(f"Ошибка загрузки учетных данных из {self.creds_file}: {e}")
            raise

    async def get_sheet_data(self, sheet_name: str) -> list[dict[str, Any]]:
        """Асинхронное получение данных из листа"""
        try:
            client = await self.client_manager.authorize()
            spreadsheet = await client.open_by_url(self.sheet_url)
            worksheet = await spreadsheet.worksheet(sheet_name)
            return await worksheet.get_all_records()
        except Exception as e:
            logger.error(f"Ошибка получения данных из '{sheet_name}': {e}")
            return []

    async def get_deadlines_data(self) -> list[dict[str, Any]]:
        """Получение данных дедлайнов с нужных листов"""
        try:
            # Параллельное получение данных
            results = await asyncio.gather(
                *[self.get_sheet_data(name) for name in self.SHEET_NAMES],
                return_exceptions=True,
            )

            # Обработка результатов и фильтрация
            all_data = []
            for i, data in enumerate(results):
                if isinstance(data, Exception):
                    logger.error(f"Ошибка листа {self.SHEET_NAMES[i]}: {data}")
                else:
                    filtered = [
                        item
                        for item in data
                        if item.get("Дисциплина") and item.get("Название ДЗ")
                    ]
                    all_data.extend(filtered)

            logger.info(f"Получено {len(all_data)} дедлайнов")
            return all_data

        except Exception as e:
            logger.exception(f"Ошибка получения дедлайнов: {e}")
            return []


# Создаем экземпляр менеджера
sheets_manager = AsyncGoogleSheetsManager()


async def main():
    """Основная асинхронная функция"""
    return await sheets_manager.get_deadlines_data()


# Запуск
if __name__ == "__main__":
    try:
        deadlines = asyncio.run(main())
        print(f"Получено записей: {len(deadlines)}")
        if deadlines:
            print(f"Первая запись: {deadlines[0]}")
    except Exception as e:
        logger.critical(f"Критическая ошибка: {e}")
