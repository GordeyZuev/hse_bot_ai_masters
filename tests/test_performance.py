"""
Тесты производительности для телеграм бота HSE.
"""
import asyncio
import pytest
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
from aiogram import Bot

from src.bot.services.notifications import NotificationService
from src.bot.services.delivery import DeliveryService
from src.db import get_db_session, UserCRUD, SubjectCRUD, DeadlineCRUD, SubscriptionCRUD


class TestPerformance:
    """Тесты производительности системы."""
    
    @pytest.fixture
    async def mock_bot(self):
        """Создает мок бота для тестов."""
        bot = AsyncMock(spec=Bot)
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=12345))
        return bot
    
    @pytest.fixture
    async def notification_service(self, mock_bot):
        """Создает сервис уведомлений для тестов."""
        return NotificationService(mock_bot)
    
    @pytest.fixture
    async def delivery_service(self, mock_bot):
        """Создает сервис доставки для тестов."""
        return DeliveryService(mock_bot)
    
    async def create_test_users(self, count: int = 800):
        """
        Создает тестовых пользователей в базе данных.
        
        Args:
            count: Количество пользователей для создания
        """
        users = []
        async with get_db_session() as session:
            for i in range(count):
                user = await UserCRUD.create(
                    session=session,
                    telegram_id=1000000 + i,
                    username=f"test_user_{i}",
                    first_name=f"Test{i}",
                    last_name="User"
                )
                users.append(user)
        return users
    
    async def create_test_subjects_and_deadlines(self, subjects_count: int = 10):
        """
        Создает тестовые дисциплины и дедлайны.
        
        Args:
            subjects_count: Количество дисциплин
        """
        subjects = []
        deadlines = []
        
        async with get_db_session() as session:
            # Создаем дисциплины
            for i in range(subjects_count):
                subject = await SubjectCRUD.create(
                    session=session,
                    name=f"Test Subject {i}",
                    description=f"Description for test subject {i}"
                )
                subjects.append(subject)
                
                # Создаем дедлайны для каждой дисциплины
                for j in range(3):  # 3 дедлайна на дисциплину
                    deadline_time = datetime.now(timezone.utc) + timedelta(hours=j+1)
                    deadline = await DeadlineCRUD.create(
                        session=session,
                        subject_id=subject.id,
                        title=f"Assignment {j+1} for {subject.name}",
                        hard_deadline=deadline_time,
                        description=f"Test assignment {j+1}"
                    )
                    deadlines.append(deadline)
        
        return subjects, deadlines
    
    async def create_test_subscriptions(self, users, subjects):
        """
        Создает подписки пользователей на дисциплины.
        
        Args:
            users: Список пользователей
            subjects: Список дисциплин
        """
        async with get_db_session() as session:
            # Каждый пользователь подписывается на случайные дисциплины
            import random
            for user in users:
                # Подписываем на 2-5 случайных дисциплин
                subject_count = random.randint(2, min(5, len(subjects)))
                selected_subjects = random.sample(subjects, subject_count)
                
                for subject in selected_subjects:
                    await SubscriptionCRUD.subscribe(
                        session=session,
                        user_id=user.id,
                        subject_id=subject.id
                    )
    
    @pytest.mark.asyncio
    async def test_database_performance(self):
        """Тестирует производительность операций с базой данных."""
        print("\n=== Testing Database Performance ===")
        
        # Тест создания пользователей
        start_time = time.time()
        users = await self.create_test_users(100)  # Создаем 100 пользователей для теста
        creation_time = time.time() - start_time
        
        print(f"Created {len(users)} users in {creation_time:.2f} seconds")
        print(f"Average: {creation_time/len(users)*1000:.2f} ms per user")
        
        # Тест поиска пользователей
        start_time = time.time()
        async with get_db_session() as session:
            for user in users[:50]:  # Тестируем поиск 50 пользователей
                found_user = await UserCRUD.get_by_telegram_id(session, user.telegram_id)
                assert found_user is not None
        
        search_time = time.time() - start_time
        print(f"Found 50 users in {search_time:.2f} seconds")
        print(f"Average: {search_time/50*1000:.2f} ms per search")
        
        # Проверяем, что время создания и поиска приемлемо
        assert creation_time < 10.0, "User creation took too long"
        assert search_time < 5.0, "User search took too long"
    
    @pytest.mark.asyncio
    async def test_notification_batch_performance(self, notification_service):
        """Тестирует производительность отправки уведомлений батчами."""
        print("\n=== Testing Notification Batch Performance ===")
        
        # Создаем тестовые данные
        users = await self.create_test_users(200)
        subjects, deadlines = await self.create_test_subjects_and_deadlines(5)
        await self.create_test_subscriptions(users, subjects)
        
        # Тестируем отправку уведомлений
        start_time = time.time()
        
        # Мокаем отправку сообщений для ускорения теста
        notification_service.delivery_service.send_message_with_retry = AsyncMock(
            return_value=(True, 12345, None)
        )
        
        stats = await notification_service.check_and_send_notifications()
        
        processing_time = time.time() - start_time
        
        print(f"Processed notifications in {processing_time:.2f} seconds")
        print(f"Stats: {stats}")
        
        if stats['notifications_sent'] > 0:
            print(f"Average: {processing_time/stats['notifications_sent']*1000:.2f} ms per notification")
        
        # Проверяем производительность
        assert processing_time < 30.0, "Notification processing took too long"
    
    @pytest.mark.asyncio
    async def test_concurrent_users_simulation(self, mock_bot):
        """Симулирует одновременную работу множества пользователей."""
        print("\n=== Testing Concurrent Users Simulation ===")
        
        async def simulate_user_action(user_id: int):
            """Симулирует действие одного пользователя."""
            async with get_db_session() as session:
                # Создаем или получаем пользователя
                user, created = await UserCRUD.get_or_create(
                    session=session,
                    telegram_id=user_id,
                    username=f"concurrent_user_{user_id}",
                    first_name=f"User{user_id}"
                )
                
                # Обновляем активность
                await UserCRUD.update_activity(session, user_id)
                
                return user.id
        
        # Симулируем 100 одновременных пользователей
        start_time = time.time()
        
        tasks = []
        for i in range(100):
            task = simulate_user_action(2000000 + i)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        concurrent_time = time.time() - start_time
        
        successful_operations = sum(1 for r in results if not isinstance(r, Exception))
        failed_operations = len(results) - successful_operations
        
        print(f"Processed {len(tasks)} concurrent operations in {concurrent_time:.2f} seconds")
        print(f"Successful: {successful_operations}, Failed: {failed_operations}")
        print(f"Average: {concurrent_time/len(tasks)*1000:.2f} ms per operation")
        
        # Проверяем, что большинство операций прошло успешно
        assert successful_operations >= len(tasks) * 0.95, "Too many failed operations"
        assert concurrent_time < 15.0, "Concurrent operations took too long"
    
    @pytest.mark.asyncio
    async def test_memory_usage_simulation(self):
        """Тестирует использование памяти при большой нагрузке."""
        print("\n=== Testing Memory Usage ===")
        
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        print(f"Initial memory usage: {initial_memory:.2f} MB")
        
        # Создаем большое количество объектов
        users = await self.create_test_users(500)
        subjects, deadlines = await self.create_test_subjects_and_deadlines(20)
        
        mid_memory = process.memory_info().rss / 1024 / 1024  # MB
        print(f"Memory after creating test data: {mid_memory:.2f} MB")
        
        # Создаем подписки
        await self.create_test_subscriptions(users, subjects)
        
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        print(f"Final memory usage: {final_memory:.2f} MB")
        print(f"Memory increase: {final_memory - initial_memory:.2f} MB")
        
        # Проверяем, что использование памяти разумно
        memory_increase = final_memory - initial_memory
        assert memory_increase < 500, f"Memory usage too high: {memory_increase:.2f} MB"
    
    @pytest.mark.asyncio
    async def test_rate_limiting_compliance(self, delivery_service):
        """Тестирует соблюдение rate limits Telegram API."""
        print("\n=== Testing Rate Limiting Compliance ===")
        
        # Мокаем отправку сообщений с задержкой
        async def mock_send_message(*args, **kwargs):
            await asyncio.sleep(0.01)  # Симулируем задержку API
            return MagicMock(message_id=12345)
        
        delivery_service.bot.send_message = mock_send_message
        
        # Подготавливаем сообщения для отправки
        messages = []
        for i in range(50):  # 50 сообщений
            messages.append({
                'chat_id': 1000000 + i,
                'text': f'Test message {i}',
                'parse_mode': 'HTML'
            })
        
        start_time = time.time()
        
        # Отправляем сообщения с соблюдением rate limits
        stats = await delivery_service.send_batch_with_rate_limiting(messages)
        
        total_time = time.time() - start_time
        
        print(f"Sent {len(messages)} messages in {total_time:.2f} seconds")
        print(f"Stats: {stats}")
        print(f"Average rate: {len(messages)/total_time:.2f} messages/second")
        
        # Проверяем, что rate не превышает лимиты Telegram (30 сообщений в секунду)
        actual_rate = len(messages) / total_time
        assert actual_rate <= 35, f"Rate too high: {actual_rate:.2f} msg/sec"
        assert stats['sent'] == len(messages), "Not all messages were sent"
    
    @pytest.mark.asyncio
    async def test_full_system_load(self, mock_bot):
        """Полный тест системы под нагрузкой 800 пользователей."""
        print("\n=== Testing Full System Load (800 users) ===")
        
        start_time = time.time()
        
        # Создаем полную нагрузку
        print("Creating 800 test users...")
        users = await self.create_test_users(800)
        
        print("Creating subjects and deadlines...")
        subjects, deadlines = await self.create_test_subjects_and_deadlines(15)
        
        print("Creating subscriptions...")
        await self.create_test_subscriptions(users, subjects)
        
        setup_time = time.time() - start_time
        print(f"Setup completed in {setup_time:.2f} seconds")
        
        # Тестируем обработку уведомлений
        notification_service = NotificationService(mock_bot)
        notification_service.delivery_service.send_message_with_retry = AsyncMock(
            return_value=(True, 12345, None)
        )
        
        processing_start = time.time()
        stats = await notification_service.check_and_send_notifications()
        processing_time = time.time() - processing_start
        
        total_time = time.time() - start_time
        
        print(f"Full system test completed in {total_time:.2f} seconds")
        print(f"Setup: {setup_time:.2f}s, Processing: {processing_time:.2f}s")
        print(f"Final stats: {stats}")
        
        # Проверяем производительность системы
        assert total_time < 120, "Full system test took too long"  # 2 минуты максимум
        assert processing_time < 60, "Notification processing took too long"  # 1 минута максимум
        
        print("✅ System successfully handles 800 users load!")


if __name__ == "__main__":
    # Запуск тестов производительности
    pytest.main([__file__, "-v", "-s"])