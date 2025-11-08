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
            logger.error(f"[SYSTEM] Ошибка загрузки учетных данных: {e}")
            raise

    async def get_sheet_data(self, sheet_name: str) -> list[dict[str, Any]]:
        """Асинхронное получение данных из листа"""
        try:
            client = await self.client_manager.authorize()
            spreadsheet = await client.open_by_url(self.sheet_url)
            worksheet = await spreadsheet.worksheet(sheet_name)
            return await worksheet.get_all_records()
        except Exception as e:
            logger.error(f"[SYSTEM] Ошибка получения данных из '{sheet_name}': {e}")
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
                    logger.error(f"[SYSTEM] Ошибка листа {self.SHEET_NAMES[i]}: {data}")
                else:
                    filtered = [
                        item
                        for item in data
                        if item.get("Дисциплина") and item.get("Название ДЗ")
                    ]
                    all_data.extend(filtered)

            logger.info(f"[SYSTEM] Получено {len(all_data)} дедлайнов")
            return all_data

        except Exception as e:
            logger.exception(f"[SYSTEM] Ошибка получения дедлайнов: {e}")
            return []

    async def get_subjects_data(self) -> list[dict[str, Any]]:
        """Получение данных дисциплин с листа "Дисциплины".

        Ожидаемые колонки: ID, Дисциплина, Курс, Модуль, Wiki, VK, YouTube, Active
        """
        try:
            rows = await self.get_sheet_data("Дисциплины")
            subjects: list[dict[str, Any]] = []

            for row in rows:
                name = (row.get("Дисциплина") or "").strip()
                year = row.get("Курс")
                if not name or year in (None, ""):
                    continue

                # Парсинг ID из таблицы (может быть пустым)
                sheet_id_raw = row.get("ID")
                try:
                    sheet_subject_id = int(sheet_id_raw) if str(sheet_id_raw).strip() != "" else None
                except Exception:
                    sheet_subject_id = None

                # Парсинг курса
                try:
                    year_int = int(str(year).strip())
                except Exception:
                    # Пропускаем некорректные строки
                    continue

                # Парсинг модулей в диапазон start/end (значение может быть int или str)
                modules_raw = row.get("Модуль")
                modules_text = ""
                if modules_raw is not None and str(modules_raw).strip() != "":
                    modules_text = str(modules_raw).strip().replace(" ", "")
                start_module = None
                end_module = None
                if modules_text:
                    if "-" in modules_text:
                        parts = modules_text.split("-", 1)
                        try:
                            start_module = int(parts[0])
                            end_module = int(parts[1])
                        except Exception:
                            start_module = None
                            end_module = None
                    else:
                        # поддержка перечня "1,2" – возьмем min/max
                        try:
                            nums = [int(x) for x in modules_text.split(",") if x]
                            if nums:
                                start_module = min(nums)
                                end_module = max(nums)
                        except Exception:
                            start_module = None
                            end_module = None

                # Ссылки могут быть не строками – приводим к str
                wiki_val = row.get("Wiki")
                vk_val = row.get("VK")
                yt_val = row.get("YouTube")
                wiki_url = (str(wiki_val).strip() if wiki_val is not None else "") or None
                vk_playlist_url = (str(vk_val).strip() if vk_val is not None else "") or None
                yt_playlist_url = (str(yt_val).strip() if yt_val is not None else "") or None

                active_raw = (row.get("Active") or "").strip().upper()
                is_active = active_raw in ("TRUE", "1", "YES")

                subjects.append(
                    {
                        "sheet_subject_id": sheet_subject_id,
                        "name": name,
                        "year": year_int,
                        "start_module": start_module,
                        "end_module": end_module,
                        "wiki_url": wiki_url,
                        "vk_playlist_url": vk_playlist_url,
                        "yt_playlist_url": yt_playlist_url,
                        "is_active": is_active,
                    }
                )

            logger.info(f"[SYSTEM] Получено {len(subjects)} дисциплин")
            return subjects
        except Exception as e:
            logger.exception(f"[SYSTEM] Ошибка получения дисциплин: {e}")
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
        logger.info(f"[SYSTEM] Получено записей: {len(deadlines)}")
        if deadlines:
            logger.info(f"Первая запись: {deadlines[0]}")
    except Exception as e:
        logger.critical(f"[SYSTEM] Критическая ошибка: {e}")
