import os
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.bot.services.admin_service import admin_service
from src.utils import get_logger
from src.core.sync.data_syncer import data_syncer
from src.bot.services.notification_sender import notification_sender

logger = get_logger()
router = Router()

ADMINS = []
try:
    admins_str = os.getenv('ADMINS', '[]')
    admins_str = admins_str.strip('[]')
    if admins_str:
        ADMINS = [int(admin_id.strip()) for admin_id in admins_str.split(',')]
except Exception as e:
    logger.error(f"Ошибка парсинга списка админов: {e}")

class BroadcastStates(StatesGroup):
    waiting_message = State()
    confirming_broadcast = State()

def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь админом"""
    return user_id in ADMINS

async def show_statistics(message_or_callback, db_user, show_back_button: bool = False):
    """Общая функция для отображения статистики"""
    try:
        stats = await admin_service.get_bot_statistics()
        text = await format_statistics_message(stats)
        
        # Создаем клавиатуру с дополнительными действиями
        builder = InlineKeyboardBuilder()
        builder.button(text="🔄 Обновить статистику", callback_data="admin_refresh_stats")
        
        if show_back_button:
            builder.button(text="🔙 Назад к админ-панели", callback_data="admin_panel")
            builder.adjust(1, 1, 1)
        else:
            builder.adjust(1, 1)
        
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.message.edit_text(text, reply_markup=builder.as_markup())
        else:
            await message_or_callback.answer(text, reply_markup=builder.as_markup())
        
        logger.info(f"Админ {db_user.tg_user_id} запросил статистику")
        
    except Exception as e:
        # Проверяем, является ли ошибка "message is not modified"
        if "message is not modified" in str(e):
            # Если сообщение не изменилось, просто логируем и ничего не показываем
            logger.info(f"Статистика для админа {db_user.tg_user_id} не изменилась")
        else:
            logger.error(f"Ошибка при получении статистики: {e}")
            error_text = "Произошла ошибка при получении статистики."
            
            if show_back_button:
                error_keyboard = InlineKeyboardBuilder().button(
                    text="🔙 Назад",
                    callback_data="admin_panel"
                ).as_markup()
            else:
                error_keyboard = None
            
            if isinstance(message_or_callback, CallbackQuery):
                await message_or_callback.message.edit_text(error_text, reply_markup=error_keyboard)
            else:
                await message_or_callback.answer(error_text)

async def perform_sync(message_or_callback, db_user, show_back_button: bool = False):
    """Общая функция для выполнения синхронизации"""
    try:
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.answer("Запускаю синхронизацию...")
        
        logger.info(f"Админ {db_user.tg_user_id} запустил синхронизацию")
        sync_result = await data_syncer.sync_data()
        success = bool(sync_result.get('success')) if isinstance(sync_result, dict) else bool(sync_result)
        
        if success:
            text = "✅ <b>Синхронизация завершена успешно!</b>\n\n"
            text += "Данные из Google Sheets обновлены в базе данных."
            try:
                # Отправка мгновенных уведомлений об изменениях при ручной синхронизации
                if isinstance(sync_result, dict):
                    changes = sync_result.get('changes', [])
                    if changes:
                        deadlines = [item['deadline'] for item in changes if 'deadline' in item]
                        if deadlines:
                            bot = message_or_callback.bot
                            await notification_sender.send_immediate_deadline_changes(bot, deadlines)
                            logger.info(f"Отправлены мгновенные уведомления об изменениях: {len(deadlines)} дедлайнов")
            except Exception as e:
                logger.warning(f"Ошибка отправки мгновенных уведомлений при ручной синхронизации: {e}")
        else:
            text = "❌ <b>Ошибка синхронизации</b>\n\n"
            text += "Не удалось синхронизировать данные. Проверьте логи для подробностей."
        
        if show_back_button:
            builder = InlineKeyboardBuilder()
            builder.button(text="🔙 Назад к админ-панели", callback_data="admin_panel")
            keyboard = builder.as_markup()
        else:
            keyboard = None
        
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.message.edit_text(text, reply_markup=keyboard)
        else:
            # Для команды /fast_sync статусное сообщение редактируем напрямую
            await message_or_callback.edit_text(text)
        
        logger.info(f"Синхронизация завершена. Результат: {'успех' if success else 'ошибка'}")
        
    except Exception as e:
        logger.error(f"Ошибка при выполнении синхронизации: {e}")
        error_text = "❌ <b>Произошла ошибка</b>\n\nНе удалось запустить синхронизацию."
        
        if show_back_button:
            error_keyboard = InlineKeyboardBuilder().button(
                text="🔙 Назад",
                callback_data="admin_panel"
            ).as_markup()
        else:
            error_keyboard = None
        
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.message.edit_text(error_text, reply_markup=error_keyboard)
        else:
            await message_or_callback.answer(f"❌ Ошибка при выполнении синхронизации: {str(e)}")

async def format_statistics_message(stats: dict) -> str:
    """Форматирование сообщения со статистикой"""
    text = "📊 <b>Статистика бота</b>\n\n"
    
    text += f"👥 <b>Пользователи:</b>\n"
    text += f"• Всего пользователей: {stats.get('total_users', 0)}\n"
    text += f"• Активных за неделю: {stats.get('active_users_week', 0)}\n"
    text += f"• Активных за месяц: {stats.get('active_users_month', 0)}\n\n"
    
    # Статистика подписок
    text += f"📚 <b>Подписки:</b>\n"
    text += f"• Всего подписок: {stats.get('total_subscriptions', 0)}\n"
    text += f"• Пользователей с подписками: {stats.get('users_with_subscriptions', 0)}\n"
    
    # Популярные предметы
    popular_subjects = stats.get('popular_subjects', [])
    if popular_subjects:
        text += f"\n<b>Популярные предметы:</b>\n"
        for i, (subject_name, count) in enumerate(popular_subjects[:5], 1):
            text += f"{i}. {subject_name} ({count})\n"
    
    
    # Статистика дедлайнов
    text += f"\n📅 <b>Дедлайны:</b>\n"
    text += f"• Всего дедлайнов: {stats.get('total_deadlines', 0)}\n"
    text += f"• Активных дедлайнов: {stats.get('active_deadlines', 0)}\n"
    
    # Статистика уведомлений
    text += f"\n🔔 <b>Уведомления:</b>\n"
    text += f"• Запланированных: {stats.get('scheduled_notifications', 0)}\n"
    
    # Системная информация
    text += f"\n⚙️ <b>Система:</b>\n"
    text += f"• Последняя синхронизация: {stats.get('last_sync', 'Неизвестно')}\n"
    
    return text

@router.message(Command("logs"))
async def cmd_logs(message: Message, db_user):
    """Обработчик команды /logs - получение логов для админов"""
    if not is_admin(db_user.tg_user_id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    try:
        await admin_service.send_logs_to_admin(message.bot, db_user.tg_user_id)
        logger.info(f"Админ {db_user.tg_user_id} запросил логи через команду")
        
    except Exception as e:
        logger.error(f"Ошибка в обработчике /logs: {e}")
        await message.answer(f"❌ Ошибка при получении логов: {str(e)}")

@router.message(Command("fast_sync"))
async def cmd_fast_sync(message: Message, db_user):
    """Обработчик команды /fast_sync - быстрая синхронизация для админов"""
    if not is_admin(db_user.tg_user_id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    # Создаем статусное сообщение
    status_message = await message.answer("🔄 <b>Запускаю синхронизацию...</b>")
    
    # Используем общую функцию синхронизации
    await perform_sync(status_message, db_user, show_back_button=False)

@router.message(Command("stats"))
async def cmd_stats(message: Message, db_user):
    """Обработчик команды /stats - статистика для админов"""
    if not is_admin(db_user.tg_user_id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    # Используем общую функцию отображения статистики
    await show_statistics(message, db_user, show_back_button=False)

@router.message(Command("broadcast"))
@router.callback_query(F.data == "admin_broadcast")
async def cmd_broadcast(event: Message | CallbackQuery, db_user, state: FSMContext):
    """Обработчик команды /broadcast - массовая рассылка"""
    if isinstance(event, CallbackQuery):
        await event.answer()
        message = event.message
    else:
        message = event
    
    if not is_admin(db_user.tg_user_id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    try:
        # Получаем количество пользователей для рассылки
        user_count = await admin_service.get_users_count()
        
        text = f"📢 <b>Массовая рассылка</b>\n\n"
        text += f"Сообщение будет отправлено <b>{user_count}</b> пользователям.\n\n"
        text += "Отправьте сообщение для рассылки или нажмите 'Отмена':"
        
        builder = InlineKeyboardBuilder()
        builder.button(text="❌ Отмена", callback_data="admin_cancel_broadcast")
        
        await state.set_state(BroadcastStates.waiting_message)
        await message.answer(text, reply_markup=builder.as_markup())
        
    except Exception as e:
        logger.error(f"Ошибка в обработчике /broadcast: {e}")
        await message.answer("Произошла ошибка при подготовке рассылки.")

@router.message(BroadcastStates.waiting_message)
async def process_broadcast_message(message: Message, db_user, state: FSMContext):
    """Обработка сообщения для рассылки"""
    if not is_admin(db_user.tg_user_id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        await state.clear()
        return
    
    try:
        # Сохраняем сообщение для рассылки
        await state.update_data(
            broadcast_text=message.html_text,
            broadcast_entities=message.entities
        )
        
        user_count = await admin_service.get_users_count()
        
        text = f"📢 <b>Подтверждение рассылки</b>\n\n"
        text += f"<b>Получателей:</b> {user_count} пользователей\n\n"
        text += f"<b>Сообщение для рассылки:</b>\n"
        text += f"<blockquote>{message.html_text[:500]}{'...' if len(message.html_text) > 500 else ''}</blockquote>\n\n"
        text += "Подтвердите отправку:"
        
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Отправить", callback_data="admin_confirm_broadcast")
        builder.button(text="❌ Отмена", callback_data="admin_cancel_broadcast")
        builder.adjust(2)
        
        await state.set_state(BroadcastStates.confirming_broadcast)
        await message.answer(text, reply_markup=builder.as_markup())
        
    except Exception as e:
        logger.error(f"Ошибка обработки сообщения для рассылки: {e}")
        await message.answer("Произошла ошибка. Попробуйте еще раз.")

@router.callback_query(F.data == "admin_confirm_broadcast")
async def callback_confirm_broadcast(callback: CallbackQuery, db_user, state: FSMContext):
    """Подтверждение и выполнение рассылки"""
    if not is_admin(db_user.tg_user_id):
        await callback.answer("❌ Нет прав доступа", show_alert=True)
        return
    
    await callback.answer("Запускаю рассылку...")
    
    try:
        data = await state.get_data()
        broadcast_text = data.get('broadcast_text')
        
        if not broadcast_text:
            await callback.message.edit_text("❌ Сообщение для рассылки не найдено.")
            await state.clear()
            return
        
        # Запускаем рассылку
        result = await admin_service.send_broadcast(
            broadcast_text,
            callback.bot,
            progress_callback=lambda sent, total: None  # Можно добавить прогресс-бар
        )
        
        success_count = result.get('success', 0)
        error_count = result.get('errors', 0)
        total_count = success_count + error_count
        
        result_text = f"📢 <b>Результат рассылки</b>\n\n"
        result_text += f"✅ Успешно отправлено: {success_count}\n"
        result_text += f"❌ Ошибок: {error_count}\n"
        result_text += f"📊 Всего: {total_count}\n"
        
        if error_count > 0:
            result_text += f"\n<i>Ошибки могут возникать из-за заблокированных ботов или удаленных аккаунтов.</i>"
        
        await callback.message.edit_text(result_text)
        await state.clear()
        
        logger.info(f"Админ {db_user.tg_user_id} выполнил рассылку: {success_count}/{total_count}")
        
    except Exception as e:
        logger.error(f"Ошибка выполнения рассылки: {e}")
        await callback.message.edit_text("❌ Произошла ошибка при выполнении рассылки.")
        await state.clear()

@router.callback_query(F.data == "admin_cancel_broadcast")
async def callback_cancel_broadcast(callback: CallbackQuery, db_user, state: FSMContext):
    """Отмена рассылки"""
    await callback.answer()
    await state.clear()
    # Просто возвращаемся в админ-панель без сообщения об отмене
    await callback_admin_panel(callback, db_user)

@router.callback_query(F.data == "admin_panel")
async def callback_admin_panel(callback: CallbackQuery, db_user):
    """Обработчик админ-панели"""
    if not is_admin(db_user.tg_user_id):
        await callback.answer("❌ Нет прав доступа", show_alert=True)
        return
    
    await callback.answer()
    
    text = "👨‍💼 <b>Админ-панель</b>\n\nВыберите действие:"
    
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="🔄 Синхронизация", callback_data="admin_sync")
    builder.button(text="📢 Broadcast", callback_data="admin_broadcast")
    builder.button(text="📄 Сегодняшние логи", callback_data="admin_logs")
    builder.button(text="🔙 Назад", callback_data="back_to_menu")
    builder.adjust(2, 2, 1)  # 2 кнопки в первых двух рядах, 1 в последнем
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())

@router.callback_query(F.data == "admin_stats")
async def callback_admin_stats(callback: CallbackQuery, db_user):
    """Обработчик кнопки статистики в админ-панели"""
    if not is_admin(db_user.tg_user_id):
        await callback.answer("❌ Нет прав доступа", show_alert=True)
        return
    
    await callback.answer("Загружаю статистику...")
    
    # Используем общую функцию отображения статистики
    await show_statistics(callback, db_user, show_back_button=True)

@router.callback_query(F.data == "admin_logs")
async def callback_admin_logs(callback: CallbackQuery, db_user):
    """Обработчик отправки логов"""
    if not is_admin(db_user.tg_user_id):
        await callback.answer("❌ Нет прав доступа", show_alert=True)
        return
    
    await callback.answer("Подготавливаю логи...")
    
    try:
        # Отправляем логи (файлы отправляются отдельными сообщениями)
        success = await admin_service.send_logs_to_admin(callback.bot, db_user.tg_user_id)
        
        # Не редактируем сообщение, так как логи отправляются отдельно
        # Просто показываем уведомление
        if success:
            await callback.answer("✅ Логи отправлены", show_alert=True)
        else:
            await callback.answer("❌ Логи не найдены", show_alert=True)
        
    except Exception as e:
        logger.error(f"Ошибка отправки логов: {e}")
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)

@router.callback_query(F.data == "admin_refresh_stats")
async def callback_admin_refresh_stats(callback: CallbackQuery, db_user):
    """Обработчик кнопки обновления статистики"""
    if not is_admin(db_user.tg_user_id):
        await callback.answer("❌ Нет прав доступа", show_alert=True)
        return
    
    await callback.answer("Обновляю статистику...")
    
    # Используем общую функцию отображения статистики
    await show_statistics(callback, db_user, show_back_button=True)

@router.callback_query(F.data == "admin_sync")
async def callback_admin_sync(callback: CallbackQuery, db_user):
    """Обработчик мгновенной синхронизации"""
    if not is_admin(db_user.tg_user_id):
        await callback.answer("❌ Нет прав доступа", show_alert=True)
        return
    
    # Используем общую функцию синхронизации
    await perform_sync(callback, db_user, show_back_button=True)

def register_admin_handlers(dp):
    """Регистрация admin handlers"""
    dp.include_router(router)