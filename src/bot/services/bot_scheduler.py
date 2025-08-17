import asyncio
import atexit
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
import pytz
from aiogram import Bot

from src.core.sync.data_syncer import data_syncer
from src.bot.services.notification_sender import notification_sender
from src.utils import get_logger

logger = get_logger()

class BotScheduler:
    """Планировщик для бота с синхронизацией и уведомлениями"""
    
    def __init__(self, bot: Bot = None):
        self.scheduler = AsyncIOScheduler(timezone=pytz.timezone('Europe/Moscow'))
        self.bot = bot
        self.is_running = False
        
        self.scheduler.add_listener(self._job_executed, EVENT_JOB_EXECUTED)
        self.scheduler.add_listener(self._job_error, EVENT_JOB_ERROR)
        
        logger.info("Планировщик бота инициализирован")
    
    def set_bot(self, bot: Bot):
        """Установить экземпляр бота"""
        self.bot = bot
    
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
    
    async def notification_job(self):
        """Задача отправки уведомлений"""
        if not self.bot:
            logger.warning("Бот не установлен, пропускаю отправку уведомлений")
            return
        
        try:
            start_time = datetime.now()
            result = await notification_sender.send_deadline_notifications(self.bot)
            duration = (datetime.now() - start_time).total_seconds()
            
            sent = result.get('sent', 0)
            errors = result.get('errors', 0)
            skipped = result.get('skipped', 0)
            
            logger.info(f"Уведомления отправлены за {duration:.2f}с: {sent} успешно, {errors} ошибок, {skipped} пропущено")
            
        except Exception as e:
            logger.error(f"Ошибка отправки уведомлений: {e}")
            raise
    
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
    
    def add_notification_job(self, interval_minutes: int = 30):
        """Добавить задачу отправки уведомлений"""
        if not self.bot:
            logger.warning("Бот не установлен, задача уведомлений не добавлена")
            return
        
        self.scheduler.add_job(
            self.notification_job,
            trigger=IntervalTrigger(interval_minutes),
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
    
    async def cleanup_job(self):
        """Задача очистки старых данных"""
        try:
            logger.info("Начинаю очистку старых данных")
            
            # Здесь можно добавить логику очистки:
            # - Удаление старых логов уведомлений
            # - Очистка неактивных пользователей
            # - Удаление устаревших дедлайнов
            
            # Пример: очистка старых логов уведомлений (старше 30 дней)
            from src.core.database import db_manager
            from src.core.models import NotificationLog
            from sqlalchemy import delete
            from datetime import timedelta
            
            async with db_manager.async_session() as session:
                cutoff_date = datetime.now() - timedelta(days=30)
                stmt = delete(NotificationLog).where(NotificationLog.created_at < cutoff_date)
                result = await session.execute(stmt)
                await session.commit()
                
                deleted_count = result.rowcount
                if deleted_count > 0:
                    logger.info(f"Удалено {deleted_count} старых записей логов уведомлений")
            
            logger.info("Очистка завершена")
            
        except Exception as e:
            logger.error(f"Ошибка очистки: {e}")
    
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
            return
        
        self.scheduler.start()
        self.is_running = True
        atexit.register(self.stop)
        logger.info("Планировщик бота запущен")
    
    def stop(self):
        """Остановка планировщика"""
        if not self.is_running:
            return
        
        self.scheduler.shutdown(wait=True)
        self.is_running = False
        logger.info("Планировщик бота остановлен")
    
    def get_jobs_info(self) -> list:
        """Получить информацию о запланированных задачах"""
        jobs_info = []
        for job in self.scheduler.get_jobs():
            next_run = job.next_run_time.strftime('%d.%m.%Y %H:%M:%S') if job.next_run_time else 'Не запланировано'
            jobs_info.append({
                'id': job.id,
                'name': job.name,
                'next_run': next_run,
                'trigger': str(job.trigger)
            })
        return jobs_info

# Создаем глобальный экземпляр планировщика
bot_scheduler = BotScheduler()

async def main():
    """Основная функция для тестирования планировщика"""
    try:
        bot_scheduler.add_immediate_sync()
        bot_scheduler.add_sync_job(1)  # Каждый час
        bot_scheduler.start()
        
        logger.info("Планировщик работает. Для остановки нажмите Ctrl+C")
        
        while bot_scheduler.is_running:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Получен сигнал прерывания")
    finally:
        bot_scheduler.stop()

if __name__ == "__main__":
    asyncio.run(main())