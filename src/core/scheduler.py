import asyncio
import atexit
from datetime import UTC, datetime

import pytz
from aiogram import Bot
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.bot.services.notification_sender import notification_sender
from src.bot.services.scheduled_notification_sender import scheduled_notification_sender
from src.core.database import db_manager
from src.core.sync.data_syncer import data_syncer
from src.utils import get_logger


logger = get_logger()


class HSEScheduler:
    """Единый планировщик для HSE бота с синхронизацией и уведомлениями"""

    def __init__(self, bot: Bot = None):
        self.scheduler = AsyncIOScheduler(
            timezone=pytz.UTC,
            job_defaults={
                "misfire_grace_time": 900,  # 15 минут допуска для выполнений после просрочки
                "coalesce": True,  # объединять пропущенные срабатывания в одно
            },
        )
        self.bot = bot
        self.is_running = False

        self.scheduler.add_listener(self._job_executed, EVENT_JOB_EXECUTED)
        self.scheduler.add_listener(self._job_error, EVENT_JOB_ERROR)

        logger.info("[SYSTEM] HSE планировщик инициализирован")

    def set_bot(self, bot: Bot):
        """Установить экземпляр бота"""
        self.bot = bot
        logger.info("[SYSTEM] Бот установлен в планировщик")

    def _job_executed(self, event):
        """Обработчик успешного выполнения задачи"""
        logger.info(f"[SYSTEM] Задача {event.job_id} выполнена")

    def _job_error(self, event):
        """Обработчик ошибки выполнения задачи"""
        logger.error(f"[SYSTEM] Ошибка в задаче '{event.job_id}': {event.exception}")

    async def sync_job(self):
        """Задача синхронизации данных с Google Sheets"""
        try:
            start_time = datetime.now(UTC)
            sync_result = await data_syncer.sync_data()
            duration = (datetime.now(UTC) - start_time).total_seconds()

            if sync_result.get("success"):
                logger.success(f"[SYSTEM] Синхронизация за {duration:.2f}с")
                if self.bot:
                    changes = sync_result.get("changes", [])
                    try:
                        # Передаем changes с информацией об изменениях
                        if changes:
                            await notification_sender.send_immediate_task_changes(
                                self.bot, changes
                            )
                    except Exception as e:
                        logger.warning(f"[SYSTEM] Ошибка групповой мгновенной отправки: {e}")
            else:
                logger.error(f"[SYSTEM] Синхронизация завершилась с ошибкой за {duration:.2f}с")

        except Exception as e:
            logger.error(f"[SYSTEM] Ошибка синхронизации: {e}")
            raise

    async def notification_job(self):
        """Задача отправки запланированных уведомлений о дедлайнах"""
        if not self.bot:
            logger.warning("[SYSTEM] Бот не установлен, пропускаю отправку уведомлений")
            return

        try:
            start_time = datetime.now(UTC)

            # Существующая логика для пользователей
            user_result = await scheduled_notification_sender.send_scheduled_notifications(
                self.bot
            )

            # Новая логика для чатов
            from src.bot.services.chat_notification_sender import (
                chat_notification_sender,
            )
            chat_result = await chat_notification_sender.send_scheduled_chat_notifications(
                self.bot
            )

            duration = (datetime.now(UTC) - start_time).total_seconds()

            user_processed = user_result.get("total_processed", 0)
            chat_processed = chat_result.get("total_processed", 0)
            total_processed = user_processed + chat_processed

            if total_processed > 0:
                logger.info(
                    f"[SYSTEM] Отправлено за {duration:.2f}с: users={user_processed}, chats={chat_processed}"
                )
            else:
                logger.debug(f"Проверка за {duration:.2f}с")

        except Exception as e:
            logger.error(f"[SYSTEM] Ошибка отправки уведомлений: {e}")
            raise

    async def cleanup_job(self):
        """Задача очистки старых данных"""
        try:
            logger.info("[SYSTEM] Начало очистки")

            # Очистка старых уведомлений (старше 30 дней)
            deleted_count = await db_manager.cleanup_old_notifications(days_old=30)
            if deleted_count > 0:
                logger.info(f"[SYSTEM] Удалено {deleted_count} уведомлений")

            logger.info("[SYSTEM] Очистка завершена")

        except Exception as e:
            logger.error(f"[SYSTEM] Ошибка очистки: {e}")

    def add_sync_job(self, interval_hours: int = 1):
        """Добавить задачу синхронизации по cron: каждые N часов на :00 (UTC)."""
        cron_hours = (
            f"*/{interval_hours}" if interval_hours and interval_hours > 0 else "*"
        )
        self.scheduler.add_job(
            self.sync_job,
            trigger=CronTrigger(hour=cron_hours, minute=0, second=0),
            id="data_sync",
            name=f"Синхронизация данных каждые {interval_hours} ч. на :00",
            replace_existing=True,
            max_instances=1,
        )
        logger.info(
            f"[SYSTEM] Добавлена задача синхронизации каждые {interval_hours} ч. на :00 (UTC)"
        )

    def add_notification_job(self, interval_minutes: int = 15):
        """Добавить задачу отправки уведомлений каждые N минут на минуте кратной N (UTC)."""
        if not self.bot:
            logger.warning("[SYSTEM] Бот не установлен, задача уведомлений не добавлена")
            return
        self.scheduler.add_job(
            self.notification_job,
            trigger=CronTrigger(minute=f"*/{interval_minutes}", second=0),
            id="send_notifications",
            name=f"Отправка уведомлений каждые {interval_minutes} минут (UTC)",
            replace_existing=True,
            max_instances=1,
        )
        logger.info(
            f"[SYSTEM] Добавлена задача уведомлений каждые {interval_minutes} мин. (UTC)"
        )

    def add_daily_cleanup_job(self, hour: int = 5, minute: int = 0):
        """Добавить ежедневную задачу очистки"""
        self.scheduler.add_job(
            self.cleanup_job,
            trigger=CronTrigger(hour=hour, minute=minute),
            id="daily_cleanup",
            name=f"Ежедневная очистка в {hour:02d}:{minute:02d}",
            replace_existing=True,
            max_instances=1,
        )
        logger.info(f"[SYSTEM] Добавлена задача очистки в {hour:02d}:{minute:02d}")

    def add_immediate_sync(self):
        """Добавить задачу немедленной синхронизации"""
        self.scheduler.add_job(
            self.sync_job,
            id="immediate_sync",
            name="Немедленная синхронизация",
            replace_existing=True,
        )
        logger.info("[SYSTEM] Добавлена задача немедленной синхронизации")

    def start(self):
        """Запуск планировщика"""
        if self.is_running:
            logger.warning("[SYSTEM] Планировщик уже запущен")
            return

        self.scheduler.start()
        self.is_running = True
        atexit.register(self.stop)
        logger.info("[SYSTEM] HSE планировщик запущен")
        # Листинг задач для валидации конфигурации
        try:
            jobs = self.scheduler.get_jobs()
            for job in jobs:
                logger.info(
                    f"[SYSTEM] Задача запланирована: id={job.id}, name={job.name}, trigger={job.trigger}, next_run_time={job.next_run_time}"
                )
        except Exception as e:
            logger.warning(f"[SYSTEM] Не удалось получить список задач планировщика: {e}")

    def stop(self):
        """Остановка планировщика"""
        if not self.is_running:
            return

        self.scheduler.shutdown(wait=True)
        self.is_running = False
        logger.info("[SYSTEM] HSE планировщик остановлен")


hse_scheduler = HSEScheduler()


async def main():
    """Основная функция для тестирования планировщика"""
    try:
        hse_scheduler.add_immediate_sync()
        hse_scheduler.add_sync_job(1)  # Каждый час
        hse_scheduler.add_daily_cleanup_job(5, 0)  # В 5:00 утра
        hse_scheduler.start()

        logger.info("[SYSTEM] Планировщик работает. Для остановки нажмите Ctrl+C")

        while hse_scheduler.is_running:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        logger.info("[SYSTEM] Получен сигнал прерывания")
    finally:
        hse_scheduler.stop()


if __name__ == "__main__":
    asyncio.run(main())
