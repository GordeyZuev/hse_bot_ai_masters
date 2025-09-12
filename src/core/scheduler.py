import asyncio
import atexit
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
import pytz
from aiogram import Bot

from src.core.database import db_manager
from src.core.sync.data_syncer import data_syncer
from src.bot.services.scheduled_notification_sender import scheduled_notification_sender
from src.utils import get_logger

logger = get_logger()

class HSEScheduler:
    """Единый планировщик для HSE бота с синхронизацией и уведомлениями"""
    
    def __init__(self, bot: Bot = None):
        self.scheduler = AsyncIOScheduler(
            timezone=pytz.UTC,
            job_defaults={
                'misfire_grace_time': 900,  # 15 минут допуска для выполнений после просрочки
                'coalesce': True            # объединять пропущенные срабатывания в одно
            }
        )
        self.bot = bot
        self.is_running = False
        
        self.scheduler.add_listener(self._job_executed, EVENT_JOB_EXECUTED)
        self.scheduler.add_listener(self._job_error, EVENT_JOB_ERROR)
        
        logger.info("HSE планировщик инициализирован")
    
    def set_bot(self, bot: Bot):
        """Установить экземпляр бота"""
        self.bot = bot
        logger.info("Бот установлен в планировщик")
    
    def _job_executed(self, event):
        """Обработчик успешного выполнения задачи"""
        logger.info(f"Задача '{event.job_id}' выполнена успешно")
    
    def _job_error(self, event):
        """Обработчик ошибки выполнения задачи"""
        logger.error(f"Ошибка в задаче '{event.job_id}': {event.exception}")
    
    async def sync_job(self):
        """Задача синхронизации данных с Google Sheets"""
        try:
            start_time = datetime.now(timezone.utc)
            success = await data_syncer.sync_data()
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            
            if success:
                logger.success(f"Синхронизация завершена за {duration:.2f}с")
            else:
                logger.error(f"Синхронизация завершилась с ошибкой за {duration:.2f}с")
                
        except Exception as e:
            logger.error(f"Ошибка синхронизации: {e}")
            raise
    
    async def notification_job(self):
        """Задача отправки запланированных уведомлений о дедлайнах"""
        if not self.bot:
            logger.warning("Бот не установлен, пропускаю отправку уведомлений")
            return
        
        try:
            start_time = datetime.now(timezone.utc)
            result = await scheduled_notification_sender.send_scheduled_notifications(self.bot)
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            
            sent = result.get('sent', 0)
            failed = result.get('failed', 0)
            skipped = result.get('skipped', 0)
            total_processed = result.get('total_processed', 0)
            
            if total_processed > 0:
                logger.info(f"Уведомления отправлены за {duration:.2f}с: {sent} успешно, {failed} неудачно, {skipped} пропущено из {total_processed}")
            else:
                logger.debug(f"Нет уведомлений для отправки (проверка за {duration:.2f}с)")
            
        except Exception as e:
            logger.error(f"Ошибка отправки уведомлений: {e}")
            raise
    
    async def cleanup_job(self):
        """Задача очистки старых данных"""
        try:
            logger.info("Начинаю очистку старых данных")
            
            # Очистка старых уведомлений (старше 30 дней)
            deleted_count = await db_manager.cleanup_old_notifications(days_old=30)
            if deleted_count > 0:
                logger.info(f"Удалено {deleted_count} старых уведомлений")
            
            logger.info("Очистка завершена")
            
        except Exception as e:
            logger.error(f"Ошибка очистки: {e}")
    
    def add_sync_job(self, interval_hours: int = 1):
        """Добавить задачу синхронизации данных"""
        self.scheduler.add_job(
            self.sync_job,
            trigger=IntervalTrigger(hours=interval_hours),
            id='data_sync',
            name=f'Синхронизация данных каждые {interval_hours} ч.',
            replace_existing=True,
            max_instances=1
        )
        logger.info(f"Добавлена задача синхронизации каждые {interval_hours} ч.")
    
    def add_notification_job(self, interval_minutes: int = 10):
        """Добавить задачу отправки уведомлений"""
        if not self.bot:
            logger.warning("Бот не установлен, задача уведомлений не добавлена")
            return
        
        job = self.scheduler.add_job(
            self.notification_job,
            trigger=IntervalTrigger(minutes=interval_minutes),
            id='send_notifications',
            name=f'Отправка уведомлений каждые {interval_minutes} мин.',
            replace_existing=True,
            max_instances=1
        )
        logger.info(
            f"Добавлена задача уведомлений каждые {interval_minutes} мин., next_run_time={getattr(job, 'next_run_time', None)}"
        )
    
    def add_daily_cleanup_job(self, hour: int = 5, minute: int = 0):
        """Добавить ежедневную задачу очистки"""
        self.scheduler.add_job(
            self.cleanup_job,
            trigger=CronTrigger(hour=hour, minute=minute),
            id='daily_cleanup',
            name=f'Ежедневная очистка в {hour:02d}:{minute:02d}',
            replace_existing=True,
            max_instances=1
        )
        logger.info(f"Добавлена задача очистки в {hour:02d}:{minute:02d}")
    
    def add_immediate_sync(self):
        """Добавить задачу немедленной синхронизации"""
        self.scheduler.add_job(
            self.sync_job,
            id='immediate_sync',
            name='Немедленная синхронизация',
            replace_existing=True
        )
        logger.info("Добавлена задача немедленной синхронизации")
    
    def start(self):
        """Запуск планировщика"""
        if self.is_running:
            logger.warning("Планировщик уже запущен")
            return
        
        self.scheduler.start()
        self.is_running = True
        atexit.register(self.stop)
        logger.info("HSE планировщик запущен")
        # Листинг задач для валидации конфигурации
        try:
            jobs = self.scheduler.get_jobs()
            for job in jobs:
                logger.info(
                    f"Задача запланирована: id={job.id}, name={job.name}, trigger={job.trigger}, next_run_time={job.next_run_time}"
                )
        except Exception as e:
            logger.warning(f"Не удалось получить список задач планировщика: {e}")
    
    def stop(self):
        """Остановка планировщика"""
        if not self.is_running:
            return
        
        self.scheduler.shutdown(wait=True)
        self.is_running = False
        logger.info("HSE планировщик остановлен")
    
hse_scheduler = HSEScheduler()

async def main():
    """Основная функция для тестирования планировщика"""
    try:
        hse_scheduler.add_immediate_sync()
        hse_scheduler.add_sync_job(1)  # Каждый час
        hse_scheduler.add_daily_cleanup_job(5, 0)  # В 5:00 утра
        hse_scheduler.start()
        
        logger.info("Планировщик работает. Для остановки нажмите Ctrl+C")
        
        while hse_scheduler.is_running:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Получен сигнал прерывания")
    finally:
        hse_scheduler.stop()

if __name__ == "__main__":
    asyncio.run(main())