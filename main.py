import asyncio
import sys
from pathlib import Path

# Добавляем текущую директорию в путь для импортов
sys.path.insert(0, str(Path(__file__).parent))

from src.core.sync.scheduler import scheduler
from src.core.database import db_manager
from src.core.sync.data_syncer import data_syncer
from src.utils import get_logger
from src.bot.bot import hse_bot

logger = get_logger()

class HSEBotSyncApp:
    """Основное приложение для синхронизации данных"""
    
    def __init__(self):
        self.scheduler = scheduler
        self.db_manager = db_manager
        self.data_syncer = data_syncer
    
    async def initialize(self):
        """Инициализация приложения"""
        await self.db_manager.ensure_initialized()
        success = await self.data_syncer.sync_data()
        
        if success:
            logger.info("Инициализация завершена успешно")
        else:
            logger.warning("Инициализация завершена с предупреждениями")
        
        return True
    
    async def start_sync_scheduler(self):
        """Запуск планировщика синхронизации"""
        try:
            self.scheduler.add_hourly_sync()
            self.scheduler.start()
            
            logger.info("Планировщик запущен. Для остановки нажмите Ctrl+C")
            while self.scheduler.is_running:
                await asyncio.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("Получен сигнал прерывания")
        finally:
            await self.shutdown()
    
    async def run_single_sync(self):
        """Выполнить одну синхронизацию и завершить работу"""
        try:
            success = await self.data_syncer.sync_data()
            return success
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """Корректное завершение работы приложения"""
        if self.scheduler.is_running:
            self.scheduler.stop()
        await self.db_manager.close()

async def main():
    """Основная функция приложения"""
    command = sys.argv[1].lower() if len(sys.argv) > 1 else "help"
    
    if command == "sync":
        logger.info("Режим: одиночная синхронизация")
        app = HSEBotSyncApp()
        await app.initialize()
        success = await app.run_single_sync()
        sys.exit(0 if success else 1)
    
    elif command == "scheduler":
        logger.info("Режим: планировщик синхронизации")
        app = HSEBotSyncApp()
        await app.initialize()
        await app.start_sync_scheduler()
    
    elif command == "bot":
        logger.info("Режим: только телеграм бот")
        await hse_bot.start_polling(with_scheduler=False)
    
    elif command == "full":
        logger.info("Режим: бот + синхронизация + уведомления")
        await hse_bot.start_polling(with_scheduler=True)
    
    else:
        print("HSE Bot - Телеграм бот для уведомлений о дедлайнах")
        print()
        print("Использование:")
        print("  python main.py bot       - запустить только телеграм бота")
        print("  python main.py sync      - выполнить одну синхронизацию")
        print("  python main.py scheduler - запустить только планировщик синхронизации")
        print("  python main.py full      - запустить бота + синхронизацию")
        print("  python main.py help      - показать эту справку")
        print()
        print("Рекомендуется использовать 'full' для полного функционала.")
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Программа завершена пользователем")
    except Exception as e:
        logger.critical(f"Критическая ошибка: {e}")
        sys.exit(1)