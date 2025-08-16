"""
Скрипт для мониторинга производительности телеграм бота HSE.
"""
import asyncio
import time
import psutil
import os
from datetime import datetime, timezone
from typing import Dict, List
import json

from src.db import get_db_session, UserCRUD, DeadlineCRUD, SentNotificationCRUD
from src.utils import main_logger


class PerformanceMonitor:
    """Монитор производительности системы."""
    
    def __init__(self):
        self.logger = main_logger
        self.process = psutil.Process(os.getpid())
        self.start_time = time.time()
        self.metrics_history = []
    
    async def collect_system_metrics(self) -> Dict:
        """Собирает системные метрики."""
        try:
            # CPU и память
            cpu_percent = self.process.cpu_percent()
            memory_info = self.process.memory_info()
            memory_mb = memory_info.rss / 1024 / 1024
            
            # Системные ресурсы
            system_cpu = psutil.cpu_percent()
            system_memory = psutil.virtual_memory()
            
            # Дисковое пространство
            disk_usage = psutil.disk_usage('/')
            
            return {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'process': {
                    'cpu_percent': cpu_percent,
                    'memory_mb': memory_mb,
                    'memory_percent': memory_info.rss / system_memory.total * 100,
                    'threads': self.process.num_threads(),
                    'open_files': len(self.process.open_files()),
                    'connections': len(self.process.connections()),
                },
                'system': {
                    'cpu_percent': system_cpu,
                    'memory_percent': system_memory.percent,
                    'memory_available_mb': system_memory.available / 1024 / 1024,
                    'disk_usage_percent': disk_usage.percent,
                    'disk_free_gb': disk_usage.free / 1024 / 1024 / 1024,
                },
                'uptime_seconds': time.time() - self.start_time
            }
        except Exception as e:
            self.logger.error(f"Error collecting system metrics: {e}")
            return {}
    
    async def collect_database_metrics(self) -> Dict:
        """Собирает метрики базы данных."""
        try:
            async with get_db_session() as session:
                # Подсчитываем основные сущности
                total_users = len(await UserCRUD.get_all_active(session))
                
                # Получаем предстоящие дедлайны
                upcoming_deadlines = await DeadlineCRUD.get_upcoming_deadlines(session, 168)  # 7 дней
                
                # TODO: Добавить методы для получения статистики
                # recent_notifications = await SentNotificationCRUD.get_recent_count(session, 24)
                # failed_notifications = await SentNotificationCRUD.get_failed_count(session, 24)
                
                return {
                    'total_active_users': total_users,
                    'upcoming_deadlines_week': len(upcoming_deadlines),
                    'recent_notifications_24h': 0,  # Заглушка
                    'failed_notifications_24h': 0,  # Заглушка
                }
        except Exception as e:
            self.logger.error(f"Error collecting database metrics: {e}")
            return {}
    
    async def collect_performance_metrics(self) -> Dict:
        """Собирает метрики производительности."""
        try:
            # Тестируем скорость операций с БД
            db_start = time.time()
            async with get_db_session() as session:
                # Простой запрос для измерения времени отклика БД
                await session.execute("SELECT 1")
            db_response_time = (time.time() - db_start) * 1000  # мс
            
            return {
                'database_response_time_ms': db_response_time,
                'active_connections': 1,  # Заглушка
                'queue_size': 0,  # Заглушка
            }
        except Exception as e:
            self.logger.error(f"Error collecting performance metrics: {e}")
            return {}
    
    async def collect_all_metrics(self) -> Dict:
        """Собирает все метрики."""
        system_metrics = await self.collect_system_metrics()
        db_metrics = await self.collect_database_metrics()
        perf_metrics = await self.collect_performance_metrics()
        
        return {
            'system': system_metrics,
            'database': db_metrics,
            'performance': perf_metrics
        }
    
    def analyze_metrics(self, metrics: Dict) -> Dict:
        """Анализирует метрики и выдает рекомендации."""
        warnings = []
        recommendations = []
        
        system = metrics.get('system', {})
        process = system.get('process', {})
        sys_info = system.get('system', {})
        
        # Анализ использования CPU
        if process.get('cpu_percent', 0) > 80:
            warnings.append("High CPU usage by bot process")
            recommendations.append("Consider optimizing CPU-intensive operations")
        
        # Анализ использования памяти
        if process.get('memory_mb', 0) > 500:
            warnings.append("High memory usage by bot process")
            recommendations.append("Check for memory leaks and optimize data structures")
        
        # Анализ системных ресурсов
        if sys_info.get('memory_percent', 0) > 85:
            warnings.append("High system memory usage")
            recommendations.append("Consider adding more RAM or optimizing memory usage")
        
        if sys_info.get('disk_usage_percent', 0) > 90:
            warnings.append("Low disk space")
            recommendations.append("Clean up old logs and temporary files")
        
        # Анализ производительности БД
        perf = metrics.get('performance', {})
        if perf.get('database_response_time_ms', 0) > 100:
            warnings.append("Slow database response time")
            recommendations.append("Optimize database queries and consider indexing")
        
        return {
            'warnings': warnings,
            'recommendations': recommendations,
            'health_score': max(0, 100 - len(warnings) * 20)  # Простая оценка здоровья
        }
    
    def save_metrics(self, metrics: Dict, filename: str = None):
        """Сохраняет метрики в файл."""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"logs/performance_metrics_{timestamp}.json"
        
        try:
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(metrics, f, indent=2, ensure_ascii=False)
            self.logger.info(f"Metrics saved to {filename}")
        except Exception as e:
            self.logger.error(f"Error saving metrics: {e}")
    
    def print_metrics_summary(self, metrics: Dict, analysis: Dict):
        """Выводит краткую сводку метрик."""
        print("\n" + "="*60)
        print("📊 PERFORMANCE METRICS SUMMARY")
        print("="*60)
        
        system = metrics.get('system', {})
        process = system.get('process', {})
        sys_info = system.get('system', {})
        db = metrics.get('database', {})
        perf = metrics.get('performance', {})
        
        print(f"🕐 Uptime: {system.get('uptime_seconds', 0):.0f} seconds")
        print(f"💾 Memory: {process.get('memory_mb', 0):.1f} MB ({process.get('memory_percent', 0):.1f}%)")
        print(f"🔥 CPU: {process.get('cpu_percent', 0):.1f}%")
        print(f"🧵 Threads: {process.get('threads', 0)}")
        print(f"📁 Open files: {process.get('open_files', 0)}")
        
        print(f"\n🖥️  System:")
        print(f"   CPU: {sys_info.get('cpu_percent', 0):.1f}%")
        print(f"   Memory: {sys_info.get('memory_percent', 0):.1f}%")
        print(f"   Disk: {sys_info.get('disk_usage_percent', 0):.1f}%")
        
        print(f"\n🗄️  Database:")
        print(f"   Active users: {db.get('total_active_users', 0)}")
        print(f"   Upcoming deadlines: {db.get('upcoming_deadlines_week', 0)}")
        print(f"   Response time: {perf.get('database_response_time_ms', 0):.1f} ms")
        
        print(f"\n🏥 Health Score: {analysis.get('health_score', 0)}/100")
        
        if analysis.get('warnings'):
            print(f"\n⚠️  Warnings:")
            for warning in analysis['warnings']:
                print(f"   • {warning}")
        
        if analysis.get('recommendations'):
            print(f"\n💡 Recommendations:")
            for rec in analysis['recommendations']:
                print(f"   • {rec}")
        
        print("="*60)
    
    async def run_continuous_monitoring(self, interval: int = 60, duration: int = 3600):
        """
        Запускает непрерывный мониторинг.
        
        Args:
            interval: Интервал между измерениями в секундах
            duration: Общая продолжительность мониторинга в секундах
        """
        print(f"🚀 Starting continuous monitoring for {duration} seconds...")
        print(f"📊 Collecting metrics every {interval} seconds")
        
        start_time = time.time()
        iteration = 0
        
        try:
            while time.time() - start_time < duration:
                iteration += 1
                print(f"\n📈 Iteration {iteration} ({time.time() - start_time:.0f}s elapsed)")
                
                # Собираем метрики
                metrics = await self.collect_all_metrics()
                analysis = self.analyze_metrics(metrics)
                
                # Добавляем в историю
                self.metrics_history.append({
                    'iteration': iteration,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'metrics': metrics,
                    'analysis': analysis
                })
                
                # Выводим сводку
                self.print_metrics_summary(metrics, analysis)
                
                # Сохраняем критические метрики
                if analysis.get('health_score', 100) < 70:
                    self.save_metrics({
                        'iteration': iteration,
                        'metrics': metrics,
                        'analysis': analysis
                    }, f"logs/critical_metrics_{iteration}.json")
                
                # Ждем до следующего измерения
                await asyncio.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n🛑 Monitoring stopped by user")
        
        # Сохраняем полную историю
        self.save_metrics({
            'monitoring_summary': {
                'start_time': datetime.fromtimestamp(start_time).isoformat(),
                'end_time': datetime.now().isoformat(),
                'duration_seconds': time.time() - start_time,
                'total_iterations': iteration
            },
            'history': self.metrics_history
        }, "logs/monitoring_history.json")
        
        print(f"\n✅ Monitoring completed. {iteration} iterations saved.")


async def run_single_check():
    """Выполняет одну проверку метрик."""
    monitor = PerformanceMonitor()
    
    print("🔍 Collecting performance metrics...")
    metrics = await monitor.collect_all_metrics()
    analysis = monitor.analyze_metrics(metrics)
    
    monitor.print_metrics_summary(metrics, analysis)
    monitor.save_metrics({'metrics': metrics, 'analysis': analysis})


async def run_load_test():
    """Выполняет нагрузочный тест."""
    monitor = PerformanceMonitor()
    
    print("🚀 Starting load test simulation...")
    
    # Симулируем нагрузку
    async def simulate_load():
        tasks = []
        for i in range(100):
            async def db_operation():
                async with get_db_session() as session:
                    await session.execute("SELECT pg_sleep(0.01)")  # 10ms задержка
            
            tasks.append(db_operation())
        
        await asyncio.gather(*tasks)
    
    # Измеряем производительность под нагрузкой
    start_time = time.time()
    
    # Метрики до нагрузки
    before_metrics = await monitor.collect_all_metrics()
    
    # Применяем нагрузку
    await simulate_load()
    
    # Метрики после нагрузки
    after_metrics = await monitor.collect_all_metrics()
    
    load_time = time.time() - start_time
    
    print(f"\n📊 Load test completed in {load_time:.2f} seconds")
    print("\n📈 BEFORE LOAD:")
    before_analysis = monitor.analyze_metrics(before_metrics)
    monitor.print_metrics_summary(before_metrics, before_analysis)
    
    print("\n📈 AFTER LOAD:")
    after_analysis = monitor.analyze_metrics(after_metrics)
    monitor.print_metrics_summary(after_metrics, after_analysis)
    
    # Сохраняем результаты нагрузочного теста
    monitor.save_metrics({
        'load_test': {
            'duration_seconds': load_time,
            'before': {'metrics': before_metrics, 'analysis': before_analysis},
            'after': {'metrics': after_metrics, 'analysis': after_analysis}
        }
    }, "logs/load_test_results.json")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "monitor":
            # Непрерывный мониторинг
            duration = int(sys.argv[2]) if len(sys.argv) > 2 else 3600  # 1 час по умолчанию
            interval = int(sys.argv[3]) if len(sys.argv) > 3 else 60   # 1 минута по умолчанию
            
            monitor = PerformanceMonitor()
            asyncio.run(monitor.run_continuous_monitoring(interval, duration))
            
        elif command == "load":
            # Нагрузочный тест
            asyncio.run(run_load_test())
            
        else:
            print("Unknown command. Use 'check', 'monitor <duration> <interval>', or 'load'")
    else:
        # Одна проверка
        asyncio.run(run_single_check())