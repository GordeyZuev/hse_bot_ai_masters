import os
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.bot.services.admin_service import admin_service
from src.utils import get_logger

logger = get_logger()
router = Router()

# Получаем список админов из переменных окружения
ADMINS = []
try:
    admins_str = os.getenv('ADMINS', '[]')
    # Убираем квадратные скобки и разделяем по запятым
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

@router.message(Command("stats"))
async def cmd_stats(message: Message, db_user):
    """Обработчик команды /stats - статистика для админов"""
    if not is_admin(db_user.tg_user_id):
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    try:
        # Получаем статистику
        stats = await admin_service.get_bot_statistics()
        
        text = "📊 <b>Статистика бота HSE</b>\n\n"
        
        # Общая статистика пользователей
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
        
        # Статистика уведомлений
        text += f"\n🔔 <b>Уведомления:</b>\n"
        text += f"• Всего настроек: {stats.get('total_notifications', 0)}\n"
        text += f"• Активных настроек: {stats.get('active_notifications', 0)}\n"
        text += f"• Пользователей с настройками: {stats.get('users_with_notifications', 0)}\n"
        
        # Статистика дедлайнов
        text += f"\n📅 <b>Дедлайны:</b>\n"
        text += f"• Всего дедлайнов: {stats.get('total_deadlines', 0)}\n"
        text += f"• Активных дедлайнов: {stats.get('active_deadlines', 0)}\n"
        text += f"• Дедлайнов на неделю: {stats.get('deadlines_week', 0)}\n"
        
        # Системная информация
        text += f"\n⚙️ <b>Система:</b>\n"
        text += f"• Последняя синхронизация: {stats.get('last_sync', 'Неизвестно')}\n"
        text += f"• Статус синхронизации: {stats.get('sync_status', 'Неизвестно')}\n"
        
        # Создаем клавиатуру с дополнительными действиями
        builder = InlineKeyboardBuilder()
        builder.button(text="🔄 Обновить", callback_data="admin_refresh_stats")
        builder.button(text="📊 Подробно", callback_data="admin_detailed_stats")
        builder.button(text="📢 Массовая рассылка", callback_data="admin_broadcast")
        builder.adjust(2, 1)
        
        await message.answer(text, reply_markup=builder.as_markup())
        
        logger.info(f"Админ {db_user.tg_user_id} запросил статистику")
        
    except Exception as e:
        logger.error(f"Ошибка в обработчике /stats: {e}")
        await message.answer("Произошла ошибка при получении статистики.")

@router.callback_query(F.data == "admin_refresh_stats")
async def callback_refresh_stats(callback: CallbackQuery, db_user):
    """Обновление статистики"""
    if not is_admin(db_user.tg_user_id):
        await callback.answer("❌ Нет прав доступа", show_alert=True)
        return
    
    await callback.answer("Обновляю статистику...")
    await cmd_stats(callback.message, db_user)

@router.callback_query(F.data == "admin_detailed_stats")
async def callback_detailed_stats(callback: CallbackQuery, db_user):
    """Подробная статистика"""
    if not is_admin(db_user.tg_user_id):
        await callback.answer("❌ Нет прав доступа", show_alert=True)
        return
    
    await callback.answer()
    
    try:
        detailed_stats = await admin_service.get_detailed_statistics()
        
        text = "📊 <b>Подробно</b>\n\n"
        
        # Статистика по дням
        text += "<b>📈 Активность по дням:</b>\n"
        daily_stats = detailed_stats.get('daily_activity', [])
        for day_data in daily_stats[-7:]:  # Последние 7 дней
            text += f"• {day_data['date']}: {day_data['users']} польз.\n"
        
        # Настройки уведомлений
        text += "\n<b>⏰ Популярные настройки уведомлений:</b>\n"
        popular_settings = detailed_stats.get('popular_notification_settings', [])
        for setting in popular_settings[:5]:
            offset_value, offset_unit, count = setting
            unit_text = {'days': 'дн.', 'hours': 'ч.', 'minutes': 'мин.'}.get(offset_unit, offset_unit)
            text += f"• За {offset_value} {unit_text}: {count} польз.\n"
        
        await callback.message.edit_text(text)
        
    except Exception as e:
        logger.error(f"Ошибка получения подробной статистики: {e}")
        await callback.answer("Ошибка получения данных", show_alert=True)

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
        user_count = await admin_service.get_active_users_count()
        
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
        
        user_count = await admin_service.get_active_users_count()
        
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
async def callback_cancel_broadcast(callback: CallbackQuery, state: FSMContext):
    """Отмена рассылки"""
    await callback.answer("Рассылка отменена")
    await callback.message.edit_text("❌ Рассылка отменена.")
    await state.clear()

def register_admin_handlers(dp):
    """Регистрация admin handlers"""
    dp.include_router(router)