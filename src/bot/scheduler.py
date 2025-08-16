"""
Планировщик задач для телеграм бота HSE.
"""
import asyncio
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from aiogram import Bot

from src.utils import scheduler_logger, settings
from src.db import get_db_session
from src.bot.services.google_sheets import GoogleSheetsClient
from src.bot.services.notifications import NotificationService


class HSEScheduler:
    """Планировщик задач для бота HSE."""
    
    def __init__(self, bot: Bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler(timezone="UTC")
        self.logger = scheduler_logger
        self.sheets_client = None
        self.notification_service = None
    
    async def setup_services(self):
        """Настраивает сервисы."""
        try:
            # Настраиваем Google Sheets клиент (опционально)
            if settings.google_sheets_url:
                self.sheets_client = GoogleSheetsClient(
                    creds_file=str(settings.google_creds_path),
                    sheet_url=settings.google_sheets_url
                )
                await self.sheets_client.initialize()
                self.logger.info("Google Sheets client initialized")
            else:
                self.logger.warning("Google Sheets URL not configured, skipping Google Sheets integration")
            
            # Настраиваем сервис уведомлений
            self.notification_service = NotificationService(self.bot)
            self.logger.info("Notification service initialized")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize services: {e}")
            raise
    
    async def sync_deadlines_from_sheets(self):
        """Синхронизирует дедлайны из Google Sheets."""
        try:
            if not self.sheets_client:
                await self.setup_services()
            
            if not self.sheets_client:
                self.logger.error("Google Sheets client not available")
                return
            
            self.logger.info("Starting deadlines sync from Google Sheets")
            
            # Получаем данные из Google Sheets
            deadlines_data = await self.sheets_client.get_deadlines()
            
            if not deadlines_data:
                self.logger.warning("No data received from Google Sheets")
                return
            
            # Обновляем данные в базе
            from src.db import DeadlineCRUD
            async for session in get_db_session():
                created, updated = await DeadlineCRUD.upsert_from_sheets(
                    session, deadlines_data
                )
                break  # Выходим после первой итерации
            
            self.logger.sheets_sync(
                created=created,
                updated=updated,
                total_records=len(deadlines_data)
            )
            
        except Exception as e:
            self.logger.error(f"Error syncing deadlines from sheets: {e}")
    
    async def check_and_send_notifications(self):
        """Проверяет дедлайны и отправляет уведомления."""
        try:
            if not self.notification_service:
                await self.setup_services()
            
            if not self.notification_service:
                self.logger.error("Notification service not available")
                return
            
            self.logger.info("Starting notification check")
            
            # Проверяем и отправляем уведомления
            stats = await self.notification_service.check_and_send_notifications()
            
            self.logger.info(
                "Notification check completed",
                **stats
            )
            
        except Exception as e:
            self.logger.error(f"Error checking notifications: {e}")
    
    async def cleanup_old_data(self):
        """Очищает старые данные из базы."""
        try:
            self.logger.info("Starting cleanup of old data")
            
            from src.db import DeadlineCRUD, SentNotificationCRUD, UserCRUD
            from datetime import timedelta
            
            async for session in get_db_session():
                cleanup_stats = {
                    'old_deadlines_removed': 0,
                    'old_notifications_removed': 0,
                    'inactive_users_processed': 0
                }
                
                # Удаляем старые дедлайны (старше 30 дней)
                cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)
                
                # TODO: Реализовать методы очистки в CRUD
                # old_deadlines = await DeadlineCRUD.get_old_deadlines(session, cutoff_date)
                # cleanup_stats['old_deadlines_removed'] = len(old_deadlines)
                
                # Удаляем старые уведомления (старше 90 дней)
                notification_cutoff = datetime.now(timezone.utc) - timedelta(days=90)
                
                # TODO: Реализовать методы очистки уведомлений
                # old_notifications = await SentNotificationCRUD.get_old_notifications(session, notification_cutoff)
                # cleanup_stats['old_notifications_removed'] = len(old_notifications)
                
                # Обрабатываем неактивных пользователей (не активны более 60 дней)
                inactive_cutoff = datetime.now(timezone.utc) - timedelta(days=60)
                
                # TODO: Реализовать обработку неактивных пользователей
                # inactive_users = await UserCRUD.get_inactive_users(session, inactive_cutoff)
                # cleanup_stats['inactive_users_processed'] = len(inactive_users)
                
                self.logger.info("Data cleanup completed", **cleanup_stats)
                break  # Выходим после первой итерации
            
        except Exception as e:
            self.logger.error(f"Error during data cleanup: {e}")
    
    async def health_check(self):
        """Проверяет состояние системы."""
        try:
            health_status = {
                'database_healthy': False,
                'sheets_healthy': False,
                'bot_healthy': False,
                'scheduler_healthy': False
            }
            
            # Проверяем подключение к базе данных
            from src.db import db_manager
            health_status['database_healthy'] = await db_manager.health_check()
            
            # Проверяем Google Sheets
            if self.sheets_client:
                health_status['sheets_healthy'] = await self.sheets_client.health_check()
            
            # Проверяем бота
            try:
                bot_info = await self.bot.get_me()
                health_status['bot_healthy'] = bool(bot_info)
            except Exception:
                health_status['bot_healthy'] = False
            
            # Проверяем планировщик
            health_status['scheduler_healthy'] = self.scheduler.running
            
            # Логируем результаты
            self.logger.info("Health check completed", **health_status)
            
            # Предупреждения о проблемах
            if not health_status['database_healthy']:
                self.logger.error("Database health check failed")
            
            if not health_status['sheets_healthy']:
                self.logger.warning("Google Sheets health check failed")
            
            if not health_status['bot_healthy']:
                self.logger.error("Bot health check failed")
            
            if not health_status['scheduler_healthy']:
                self.logger.error("Scheduler is not running")
                
        except Exception as e:
            self.logger.error(f"Error during health check: {e}")
    
    async def generate_statistics(self):
        """Генерирует статистику использования бота."""
        try:
            self.logger.info("Generating usage statistics")
            
            from src.db import UserCRUD, SubscriptionCRUD, DeadlineCRUD, SentNotificationCRUD
            
            async for session in get_db_session():
                stats = {}
                
                # Статистика пользователей
                all_users = await UserCRUD.get_all_active(session)
                stats['total_active_users'] = len(all_users)
                
                # Статистика подписок
                # TODO: Добавить метод для получения общей статистики подписок
                # subscription_stats = await SubscriptionCRUD.get_subscription_stats(session)
                # stats.update(subscription_stats)
                
                # Статистика дедлайнов
                upcoming_deadlines = await DeadlineCRUD.get_upcoming_deadlines(session, 168)  # 7 дней
                stats['upcoming_deadlines_week'] = len(upcoming_deadlines)
                
                # Статистика уведомлений за последние 24 часа
                # TODO: Добавить метод для получения статистики уведомлений
                # notification_stats = await SentNotificationCRUD.get_daily_stats(session)
                # stats.update(notification_stats)
                
                self.logger.info("Usage statistics generated", **stats)
                break  # Выходим после первой итерации
            
        except Exception as e:
            self.logger.error(f"Error generating statistics: {e}")
    
    def start(self):
        """Запускает планировщик с настроенными задачами."""
        try:
            # Синхронизация с Google Sheets каждые 30 минут
            self.scheduler.add_job(
                self.sync_deadlines_from_sheets,
                trigger=IntervalTrigger(minutes=30),
                id="sync_deadlines",
                name="Sync deadlines from Google Sheets",
                replace_existing=True,
                max_instances=1,  # Предотвращаем параллельное выполнение
                coalesce=True     # Объединяем пропущенные запуски
            )
            
            # Проверка уведомлений каждые 15 минут
            self.scheduler.add_job(
                self.check_and_send_notifications,
                trigger=IntervalTrigger(minutes=15),
                id="check_notifications",
                name="Check and send notifications",
                replace_existing=True,
                max_instances=1,
                coalesce=True
            )
            
            # Очистка старых данных каждый день в 3:00 UTC
            self.scheduler.add_job(
                self.cleanup_old_data,
                trigger=CronTrigger(hour=3, minute=0),
                id="cleanup_data",
                name="Cleanup old data",
                replace_existing=True,
                max_instances=1
            )
            
            # Health check каждые 5 минут
            self.scheduler.add_job(
                self.health_check,
                trigger=IntervalTrigger(minutes=5),
                id="health_check",
                name="System health check",
                replace_existing=True,
                max_instances=1,
                coalesce=True
            )
            
            # Генерация статистики каждый час
            self.scheduler.add_job(
                self.generate_statistics,
                trigger=IntervalTrigger(hours=1),
                id="generate_statistics",
                name="Generate usage statistics",
                replace_existing=True,
                max_instances=1,
                coalesce=True
            )
            
            self.scheduler.start()
            self.logger.info("Scheduler started with all jobs")
            
            # Выводим информацию о запланированных задачах
            jobs = self.scheduler.get_jobs()
            for job in jobs:
                self.logger.info(f"Scheduled job: {job.name} (ID: {job.id})")
            
        except Exception as e:
            self.logger.error(f"Error starting scheduler: {e}")
            raise
    
    def shutdown(self):
        """Останавливает планировщик."""
        try:
            if self.scheduler.running:
                self.scheduler.shutdown(wait=True)
                self.logger.info("Scheduler stopped")
        except Exception as e:
            self.logger.error(f"Error stopping scheduler: {e}")
    
    def get_job_status(self) -> dict:
        """Возвращает статус всех задач планировщика."""
        try:
            jobs = self.scheduler.get_jobs()
            job_status = {}
            
            for job in jobs:
                job_status[job.id] = {
                    'name': job.name,
                    'next_run': job.next_run_time.isoformat() if job.next_run_time else None,
                    'trigger': str(job.trigger),
                    'max_instances': job.max_instances,
                    'coalesce': job.coalesce
                }
            
            return job_status
            
        except Exception as e:
            self.logger.error(f"Error getting job status: {e}")
            return {}


async def setup_scheduler(bot: Bot) -> HSEScheduler:
    """
    Настраивает и запускает планировщик задач.
    
    Args:
        bot: Экземпляр бота
        
    Returns:
        Настроенный планировщик
    """
    scheduler = HSEScheduler(bot)
    
    # Инициализируем сервисы
    await scheduler.setup_services()
    
    # Запускаем планировщик
    scheduler.start()
    
    # Выполняем первую синхронизацию (если Google Sheets настроен)
    if scheduler.sheets_client:
        await scheduler.sync_deadlines_from_sheets()
    
    # Выполняем первую проверку уведомлений
    await scheduler.check_and_send_notifications()
    
    return scheduler