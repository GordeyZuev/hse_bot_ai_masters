"""
Сервис для работы с Google Sheets API.
"""
import asyncio
from typing import List, Dict, Optional
import gspread_asyncio
from google.oauth2.service_account import Credentials
from datetime import datetime, timezone
import pytz

from src.utils import sheets_logger


class GoogleSheetsClient:
    """Клиент для работы с Google Sheets."""
    
    def __init__(self, creds_file: str, sheet_url: str):
        self.creds_file = creds_file
        self.sheet_url = sheet_url
        self.agcm = None
        self.sheet = None
        self.logger = sheets_logger
    
    async def _get_creds(self):
        """Получает credentials для Google Sheets API."""
        def get_creds():
            return Credentials.from_service_account_file(
                self.creds_file,
                scopes=[
                    "https://www.googleapis.com/auth/spreadsheets.readonly",
                    "https://www.googleapis.com/auth/drive.readonly"
                ]
            )
        return get_creds
    
    async def initialize(self):
        """Инициализирует асинхронный клиент Google Sheets."""
        try:
            creds_func = await self._get_creds()
            self.agcm = gspread_asyncio.AsyncioGspreadClientManager(creds_func)
            agc = await self.agcm.authorize()
            spreadsheet = await agc.open_by_url(self.sheet_url)
            self.sheet = await spreadsheet.get_worksheet(0)  # Получаем первый лист
            
            self.logger.info("Google Sheets client initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize Google Sheets client: {e}")
            raise
    
    async def get_deadlines(self) -> List[Dict]:
        """
        Асинхронно получает данные о дедлайнах из таблицы.
        
        Returns:
            Список словарей с данными о дедлайнах
        """
        try:
            if not self.sheet:
                await self.initialize()
            
            # Получаем все записи из таблицы
            records = await self.sheet.get_all_records()
            
            # Фильтруем и обрабатываем данные
            processed_records = []
            for record in records:
                processed_record = self._process_record(record)
                if processed_record:
                    processed_records.append(processed_record)
            
            self.logger.info(
                f"Successfully fetched {len(processed_records)} deadlines from Google Sheets",
                total_records=len(records),
                processed_records=len(processed_records)
            )
            
            return processed_records
            
        except Exception as e:
            self.logger.error(f"Error fetching deadlines from Google Sheets: {e}")
            return []
    
    def _process_record(self, record: Dict) -> Optional[Dict]:
        """
        Обрабатывает одну запись из Google Sheets.
        
        Args:
            record: Словарь с данными из строки таблицы
            
        Returns:
            Обработанный словарь или None, если запись некорректна
        """
        try:
            # Извлекаем данные из записи
            external_id = str(record.get('ID', '')).strip()
            subject_name = str(record.get('Дисциплина', '')).strip()
            title = str(record.get('Название ДЗ', '')).strip()
            source_link = str(record.get('Источник \n(Link)', '') or record.get('Источник (Link)', '')).strip()
            soft_deadline_str = str(record.get('Мягкий \nДедлайн', '') or record.get('Мягкий Дедлайн', '')).strip()
            hard_deadline_str = str(record.get('Жесткий \nДедлайн', '') or record.get('Жесткий Дедлайн', '')).strip()
            days_until_str = str(record.get('Дней до', '')).strip()
            notes = str(record.get('Примечание', '')).strip()
            
            # Проверяем обязательные поля
            if not all([subject_name, title, hard_deadline_str]):
                self.logger.debug(
                    f"Skipping incomplete record",
                    external_id=external_id,
                    subject_name=subject_name,
                    title=title,
                    hard_deadline_str=hard_deadline_str
                )
                return None
            
            # Парсим даты
            hard_deadline = self._parse_datetime(hard_deadline_str)
            if not hard_deadline:
                self.logger.warning(
                    f"Failed to parse hard deadline",
                    external_id=external_id,
                    hard_deadline_str=hard_deadline_str
                )
                return None
            
            soft_deadline = None
            if soft_deadline_str:
                soft_deadline = self._parse_datetime(soft_deadline_str)
            
            # Парсим количество дней до дедлайна
            days_until = None
            if days_until_str and days_until_str.isdigit():
                days_until = int(days_until_str)
            
            # Формируем обработанную запись
            processed_record = {
                'external_id': external_id or None,
                'subject_name': subject_name,
                'title': title,
                'source_link': source_link or None,
                'soft_deadline': soft_deadline,
                'hard_deadline': hard_deadline,
                'days_until': days_until,
                'notes': notes or None
            }
            
            return processed_record
            
        except Exception as e:
            self.logger.error(
                f"Error processing record: {e}",
                record=str(record)[:200]  # Ограничиваем длину для логов
            )
            return None
    
    def _parse_datetime(self, date_str: str) -> Optional[datetime]:
        """
        Парсит строку с датой и временем.
        
        Args:
            date_str: Строка с датой
            
        Returns:
            Объект datetime или None, если не удалось распарсить
        """
        if not date_str:
            return None
        
        # Список возможных форматов даты
        date_formats = [
            "%d.%m.%Y %H:%M",      # 25.12.2024 23:59
            "%d.%m.%Y",            # 25.12.2024
            "%d/%m/%Y %H:%M",      # 25/12/2024 23:59
            "%d/%m/%Y",            # 25/12/2024
            "%Y-%m-%d %H:%M:%S",   # 2024-12-25 23:59:00
            "%Y-%m-%d %H:%M",      # 2024-12-25 23:59
            "%Y-%m-%d",            # 2024-12-25
            "%d-%m-%Y %H:%M",      # 25-12-2024 23:59
            "%d-%m-%Y",            # 25-12-2024
        ]
        
        for date_format in date_formats:
            try:
                # Парсим дату
                dt = datetime.strptime(date_str, date_format)
                
                # Если время не указано, устанавливаем 23:59
                if date_format in ["%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"]:
                    dt = dt.replace(hour=23, minute=59, second=59)
                
                # Устанавливаем часовой пояс (Moscow)
                moscow_tz = pytz.timezone('Europe/Moscow')
                dt = moscow_tz.localize(dt)
                
                # Конвертируем в UTC
                dt_utc = dt.astimezone(pytz.UTC)
                
                return dt_utc
                
            except ValueError:
                continue
        
        # Если ни один формат не подошел, пробуем dateutil
        try:
            from dateutil import parser
            dt = parser.parse(date_str, dayfirst=True)
            
            # Если часовой пояс не указан, считаем что это Moscow
            if dt.tzinfo is None:
                moscow_tz = pytz.timezone('Europe/Moscow')
                dt = moscow_tz.localize(dt)
            
            # Конвертируем в UTC
            dt_utc = dt.astimezone(pytz.UTC)
            return dt_utc
            
        except Exception:
            self.logger.warning(f"Failed to parse date string: {date_str}")
            return None
    
    async def get_sheet_info(self) -> Dict:
        """
        Получает информацию о таблице.
        
        Returns:
            Словарь с информацией о таблице
        """
        try:
            if not self.sheet:
                await self.initialize()
            
            # Получаем базовую информацию
            sheet_info = {
                'title': self.sheet.title,
                'row_count': self.sheet.row_count,
                'col_count': self.sheet.col_count,
                'url': self.sheet_url
            }
            
            # Получаем заголовки
            try:
                headers = await self.sheet.row_values(1)
                sheet_info['headers'] = headers
            except Exception:
                sheet_info['headers'] = []
            
            return sheet_info
            
        except Exception as e:
            self.logger.error(f"Error getting sheet info: {e}")
            return {}
    
    async def health_check(self) -> bool:
        """
        Проверяет доступность Google Sheets.
        
        Returns:
            True, если сервис доступен
        """
        try:
            if not self.sheet:
                await self.initialize()
            
            # Пробуем получить первую строку
            await self.sheet.row_values(1)
            return True
            
        except Exception as e:
            self.logger.error(f"Google Sheets health check failed: {e}")
            return False


# Пример использования
async def main():
    """Пример использования клиента Google Sheets."""
    client = GoogleSheetsClient(
        "config/creds.json", 
        "https://docs.google.com/spreadsheets/d/15v5M7_GnBxX58dmHATSoLVeiWiX5DsmwR-o0Z3W5mJE/edit?usp=sharing"
    )
    
    try:
        # Получаем информацию о таблице
        sheet_info = await client.get_sheet_info()
        print("Sheet info:", sheet_info)
        
        # Получаем дедлайны
        deadlines = await client.get_deadlines()
        print(f"Found {len(deadlines)} deadlines")
        
        # Выводим первые несколько записей
        for i, deadline in enumerate(deadlines[:3]):
            print(f"{i+1}. {deadline}")
            
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())