import asyncio
import atexit
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
import pytz
from aiogram import Bot
from sqlalchemy import delete

from src.core.database import db_manager
from src.core.models import NotificationLog
from src.core.sync.data_syncer import data_syncer
from src.utils import get_logger

logger = get_logger()

class HSEScheduler:
    """Единый планировщик для HSE бота с синхронизацией и уведомлениями"""
    
    def __init__(self, bot: Bot = None):
        self.scheduler = AsyncIOScheduler(timezone=pytz.timezone('Europe/Moscow'))
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
            start_time = datetime.now(pytz.timezone('Europe/Moscow'))
            success = await data_syncer.sync_data()
            duration = (datetime.now(pytz.timezone('Europe/Moscow')) - start_time).total_seconds()
            
            if success:
                logger.success(f"Синхронизация завершена за {duration:.2f}с")
            else:
                logger.error(f"Синхронизация завершилась с ошибкой за {duration:.2f}с")
                
        except Exception as e:
            logger.error(f"Ошибка синхронизации: {e}")
            raise
    
    async def notification_job(self):
        """Задача отправки уведомлений о дедлайнах"""
        if not self.bot:
            logger.warning("Бот не установлен, пропускаю отправку уведомлений")
            return
        
        try:
            from src.bot.services.notification_sender import notification_sender
            start_time = datetime.now(pytz.timezone('Europe/Moscow'))
            result = await notification_sender.send_deadline_notifications(self.bot)
            duration = (datetime.now(pytz.timezone('Europe/Moscow')) - start_time).total_seconds()
            
            sent = result.get('sent', 0)
            errors = result.get('errors', 0)
            skipped = result.get('skipped', 0)
            
            logger.info(f"Уведомления отправлены за {duration:.2f}с: {sent} успешно, {errors} ошибок, {skipped} пропущено")
            
        except Exception as e:
            logger.error(f"Ошибка отправки уведомлений: {e}")
            raise
    
    async def cleanup_job(self):
        """Задача очистки старых данных"""
        try:
            logger.info("Начинаю очистку старых данных")
            
            # Очистка старых логов уведомлений (старше 30 дней)
            async with db_manager.async_session() as session:
                cutoff_date = datetime.now(pytz.timezone('Europe/Moscow')) - timedelta(days=30)
                stmt = delete(NotificationLog).where(NotificationLog.created_at < cutoff_date)
                result = await session.execute(stmt)
                await session.commit()
                
                deleted_count = result.rowcount
                if deleted_count > 0:
                    logger.info(f"Удалено {deleted_count} старых записей логов уведомлений")
            
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
        
        self.scheduler.add_job(
            self.notification_job,
            trigger=IntervalTrigger(minutes=interval_minutes),
            id='send_notifications',
            name=f'Отправка уведомлений каждые {interval_minutes} мин.',
            replace_existing=True,
            max_instances=1
        )
        logger.info(f"Добавлена задача уведомлений каждые {interval_minutes} мин.")
    
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
    
    def stop(self):
        """Остановка планировщика"""
        if not self.is_running:
            return
        
        self.scheduler.shutdown(wait=True)
        self.is_running = False
        logger.info("HSE планировщик остановлен")
    
    def get_jobs_info(self) -> list:
        """Получить информацию о запланированных задачах"""
        jobs_info = []
        for job in self.scheduler.get_jobs():
            if job.next_run_time:
                moscow_time = job.next_run_time.astimezone(pytz.timezone('Europe/Moscow'))
                next_run = moscow_time.strftime('%d.%m.%Y %H:%M:%S МСК')
            else:
                next_run = 'Не запланировано'
            jobs_info.append({
                'id': job.id,
                'name': job.name,
                'next_run': next_run,
                'trigger': str(job.trigger)
            })
        return jobs_info
    
    # Методы для совместимости со старым API
    def add_hourly_sync(self):
        """Добавить задачу синхронизации каждый час (совместимость)"""
        self.add_sync_job(1)
    
    def add_notification_check(self):
        """Добавить задачу проверки уведомлений каждые 30 минут (совместимость)"""
        self.add_notification_job(10)

# Создаем глобальный экземпляр планировщика
hse_scheduler = HSEScheduler()

# Алиасы для совместимости
scheduler = hse_scheduler
bot_scheduler = hse_scheduler

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