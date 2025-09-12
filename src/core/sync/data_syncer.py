import asyncio
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
import re
from dateutil import parser

from src.core.sync.gsheets_syncer import sheets_manager
from src.core.database import db_manager
from src.bot.services.notification_scheduler_service import notification_scheduler_service
from src.utils import get_logger
from src.utils.time import localize_naive_and_convert_to_utc

logger = get_logger()

class DataSyncer:
    def __init__(self):
        pass
    
    def parse_date(self, date_str: str) -> Optional[datetime]:
        """Парсинг даты из различных форматов"""
        if not date_str or not date_str.strip():
            return None
        
        try:
            date_str = date_str.strip()
            parsed_date = parser.parse(date_str, dayfirst=True)
            
            # Устанавливаем время 23:59 если его нет
            if parsed_date.time() == datetime.min.time():
                parsed_date = parsed_date.replace(hour=23, minute=59)
            
            source_tz = os.getenv('TIMEZONE', 'Europe/Moscow')
            return localize_naive_and_convert_to_utc(parsed_date, source_tz)
        except Exception as e:
            logger.warning(f"Не удалось распарсить дату '{date_str}': {e}")
            return None
    
    def extract_module_from_subject(self, subject_name: str) -> int:
        """Извлечение модуля из названия предмета"""
        module_match = re.search(r'(\d+)\s*модуль', subject_name, re.IGNORECASE)
        return int(module_match.group(1)) if module_match else 1
    
    def clean_subject_name(self, subject_name: str) -> str:
        """Очистка названия предмета от лишней информации"""
        cleaned = re.sub(r'\s*\d+\s*модуль\s*', '', subject_name, flags=re.IGNORECASE)
        return re.sub(r'\s+', ' ', cleaned).strip()
    
    def extract_sheet_row_id(self, row_data: Dict[str, Any]) -> int:
        """Извлечение ID строки из данных Google Sheets"""
        for field in ['ID', 'id', 'Row ID', 'Номер строки', '№']:
            if field in row_data and row_data[field]:
                try:
                    return int(row_data[field])
                except (ValueError, TypeError):
                    continue
        
        # Используем хеш если ID не найден
        return abs(hash(str(sorted(row_data.items())))) % 1000000
    
    async def transform_sheets_data_to_db_format(self, sheets_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Преобразование данных из Google Sheets в формат базы данных"""
        await db_manager.ensure_initialized()
        transformed_data = []
        
        for row_data in sheets_data:
            try:
                subject_name_raw = row_data.get('Дисциплина', '').strip()
                hw_name = row_data.get('Название ДЗ', '').strip()
                
                if not subject_name_raw or not hw_name:
                    continue
                
                # Обработка предмета
                #module = self.extract_module_from_subject(subject_name_raw)
                subject_name = self.clean_subject_name(subject_name_raw)
                
                subject = await db_manager.get_or_create_subject(
                    name=subject_name,
                )
                
                # Формирование данных дедлайна
                deadline_data = {
                    'subject_id': subject.id,
                    'hw_name': hw_name,
                    'source_link': row_data.get('Источник (Link)', '').strip() or None,
                    'soft_deadline_ts': self.parse_date(row_data.get('Мягкий Дедлайн', '')),
                    'hard_deadline_ts': self.parse_date(row_data.get('Жесткий Дедлайн', '')),
                    'note': row_data.get('Комментарий', '').strip() or '',
                    'sheet_row_id': self.extract_sheet_row_id(row_data)
                }
                
                transformed_data.append(deadline_data)
                
            except Exception as e:
                logger.error(f"Ошибка преобразования строки {row_data}: {e}")
                continue
        
        logger.info(f"Преобразовано {len(transformed_data)} записей из {len(sheets_data)}")
        return transformed_data
    
    async def sync_data(self) -> bool:
        """Основная функция синхронизации данных"""
        try:
            logger.info("Начало синхронизации данных")
            await db_manager.ensure_initialized()
            
            # Получение и преобразование данных
            sheets_data = await sheets_manager.get_deadlines_data()
            if not sheets_data:
                logger.warning("Нет данных из Google Sheets")
                return False
            
            db_data = await self.transform_sheets_data_to_db_format(sheets_data)
            if not db_data:
                logger.warning("Нет данных для синхронизации")
                return False
            
            # Синхронизация
            synced_count = 0
            scheduled_notifications_count = 0
            current_sheet_row_ids = []
            
            for deadline_data in db_data:
                deadline, was_changed = await db_manager.upsert_deadline(deadline_data)
                if deadline:
                    synced_count += 1
                    current_sheet_row_ids.append(deadline.sheet_row_id)
                    
                    # Планируем уведомления только если были изменения или новая запись
                    if was_changed:
                        try:
                            notifications_count = await notification_scheduler_service.reschedule_notifications_for_updated_deadline(deadline)
                            scheduled_notifications_count += notifications_count
                        except Exception as e:
                            logger.error(f"Ошибка планирования уведомлений для дедлайна {deadline.id}: {e}")
            
            await db_manager.delete_outdated_deadlines(current_sheet_row_ids)
            logger.info(f"Синхронизировано {synced_count} дедлайнов, запланировано {scheduled_notifications_count} уведомлений")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка синхронизации: {e}")
            return False

data_syncer = DataSyncer()

async def main():
    """Функция для тестирования синхронизации"""
    success = await data_syncer.sync_data()
    print("Синхронизация выполнена успешно!" if success else "Ошибка синхронизации")

if __name__ == "__main__":
    asyncio.run(main())