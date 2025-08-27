import asyncio
import atexit
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
import pytz

from src.core.sync.data_syncer import data_syncer
from src.utils import get_logger

logger = get_logger()

class SyncScheduler:
    def __init__(self):
        self.scheduler = AsyncIOScheduler(timezone=pytz.timezone('Europe/Moscow'))
        self.is_running = False
        
        self.scheduler.add_listener(self._job_executed, EVENT_JOB_EXECUTED)
        self.scheduler.add_listener(self._job_error, EVENT_JOB_ERROR)
        
        logger.info("Планировщик синхронизации инициализирован с APScheduler")
    
    def _job_executed(self, event):
        """Обработчик успешного выполнения задачи"""
        logger.info(f"Задача '{event.job_id}' выполнена успешно")
    
    def _job_error(self, event):
        """Обработчик ошибки выполнения задачи"""
        logger.error(f"Ошибка в задаче '{event.job_id}': {event.exception}")
    
    async def sync_job(self):
        """Задача синхронизации данных"""
        try:
            start_time = datetime.now()
            success = await data_syncer.sync_data()
            duration = (datetime.now() - start_time).total_seconds()
            
            if success:
                logger.success(f"Синхронизация завершена за {duration:.2f}с")
            else:
                logger.error(f"Синхронизация завершилась с ошибкой за {duration:.2f}с")
                
        except Exception as e:
            logger.error(f"Ошибка синхронизации: {e}")
            raise
    
    def add_hourly_sync(self):
        """Добавить задачу синхронизации каждый час"""
        logger.info("Добавлена задача синхронизации каждый час")
        self.scheduler.add_job(
            self.sync_job,
            trigger=IntervalTrigger(hours=1),  # Синхронизация каждый час
            id='hourly_sync',
            name='Синхронизация данных каждый час',
            replace_existing=True,
            max_instances=1
        )
    
    def add_notification_check(self):
        """Добавить задачу проверки уведомлений каждые 30 минут"""
        logger.info("Добавлена задача проверки уведомлений каждые 30 минут")
        self.scheduler.add_job(
            self.notification_job,
            trigger=IntervalTrigger(minutes=30),  # Проверка уведомлений каждые 30 минут
            id='notification_check',
            name='Проверка уведомлений каждые 30 минут',
            replace_existing=True,
            max_instances=1
        )
    
    async def notification_job(self):
        """Задача проверки и отправки уведомлений"""
        try:
            from src.bot.services.notification_sender import notification_sender
            start_time = datetime.now()
            
            # Отправляем уведомления
            sent_count = await notification_sender.send_deadline_notifications()
            
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"Проверка уведомлений завершена за {duration:.2f}с, отправлено: {sent_count}")
                
        except Exception as e:
            logger.error(f"Ошибка проверки уведомлений: {e}")
            raise
    
    def add_immediate_sync(self):
        """Добавить задачу немедленной синхронизации"""
        self.scheduler.add_job(
            self.sync_job,
            id='immediate_sync',
            name='Немедленная синхронизация',
            replace_existing=True
        )
    
    def start(self):
        """Запуск планировщика"""
        if self.is_running:
            return
        
        self.scheduler.start()
        self.is_running = True
        atexit.register(self.stop)
        logger.info("Планировщик запущен")
    
    def stop(self):
        """Остановка планировщика"""
        if not self.is_running:
            return
        
        self.scheduler.shutdown(wait=True)
        self.is_running = False
        logger.info("Планировщик остановлен")
    

# Создаем глобальный экземпляр планировщика
scheduler = SyncScheduler()

async def main():
    """Основная функция"""
    try:
        scheduler.add_immediate_sync()
        scheduler.add_hourly_sync()
        scheduler.add_notification_check()
        scheduler.start()
        
        logger.info("Планировщик работает. Для остановки нажмите Ctrl+C")
        
        while scheduler.is_running:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Получен сигнал прерывания")
    finally:
        scheduler.stop()

if __name__ == "__main__":
    asyncio.run(main())