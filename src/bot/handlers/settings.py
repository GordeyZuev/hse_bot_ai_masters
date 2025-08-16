"""
Хендлеры для настроек уведомлений.
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.db import UserCRUD, NotificationSettingsCRUD, get_db_session
from src.utils import bot_logger


router = Router()


class SettingsStates(StatesGroup):
    """Состояния для настройки уведомлений."""
    setting_notifications_count = State()
    setting_first_notification_time = State()
    setting_second_notification_time = State()


@router.message(Command("settings"))
async def settings_command_handler(message: Message):
    """Обработчик команды /settings."""
    await show_settings_menu(message)


@router.callback_query(F.data == "settings")
async def settings_callback_handler(callback: CallbackQuery):
    """Обработчик callback для настроек."""
    await show_settings_menu(callback.message, callback)


@router.callback_query(F.data == "toggle_notifications")
async def toggle_notifications_handler(callback: CallbackQuery):
    """Обработчик включения/выключения уведомлений."""
    user = callback.from_user
    
    try:
        async with get_db_session() as session:
            # Получаем пользователя
            db_user = await UserCRUD.get_by_telegram_id(session, user.id)
            if not db_user:
                await callback.answer("❌ Пользователь не найден")
                return
            
            # Получаем настройки
            settings_obj, _ = await NotificationSettingsCRUD.get_or_create(session, db_user.id)
            
            # Переключаем состояние
            new_state = not settings_obj.notifications_enabled
            await NotificationSettingsCRUD.update(
                session, db_user.id, notifications_enabled=new_state
            )
            
            status_text = "включены" if new_state else "выключены"
            await callback.answer(f"✅ Уведомления {status_text}")
            
            bot_logger.user_action(
                user_id=user.id,
                action="notifications_toggled",
                enabled=new_state
            )
            
            # Обновляем меню
            await show_settings_menu(callback.message, callback)
            
    except Exception as e:
        bot_logger.error(f"Error toggling notifications: {e}", user_id=user.id)
        await callback.answer("❌ Ошибка при изменении настроек")


@router.callback_query(F.data.startswith("set_notifications_count:"))
async def set_notifications_count_handler(callback: CallbackQuery):
    """Обработчик установки количества уведомлений."""
    user = callback.from_user
    count = int(callback.data.split(":")[1])
    
    try:
        async with get_db_session() as session:
            # Получаем пользователя
            db_user = await UserCRUD.get_by_telegram_id(session, user.id)
            if not db_user:
                await callback.answer("❌ Пользователь не найден")
                return
            
            # Обновляем настройки
            await NotificationSettingsCRUD.update(
                session, db_user.id, notifications_count=count
            )
            
            await callback.answer(f"✅ Количество уведомлений: {count}")
            
            bot_logger.user_action(
                user_id=user.id,
                action="notifications_count_changed",
                count=count
            )
            
            # Обновляем меню
            await show_settings_menu(callback.message, callback)
            
    except Exception as e:
        bot_logger.error(f"Error setting notifications count: {e}", user_id=user.id)
        await callback.answer("❌ Ошибка при изменении настроек")


@router.callback_query(F.data.startswith("set_first_notification:"))
async def set_first_notification_handler(callback: CallbackQuery):
    """Обработчик установки времени первого уведомления."""
    user = callback.from_user
    hours = int(callback.data.split(":")[1])
    
    try:
        async with get_db_session() as session:
            # Получаем пользователя
            db_user = await UserCRUD.get_by_telegram_id(session, user.id)
            if not db_user:
                await callback.answer("❌ Пользователь не найден")
                return
            
            # Обновляем настройки
            await NotificationSettingsCRUD.update(
                session, db_user.id, first_notification_hours=hours
            )
            
            time_text = f"{hours} ч." if hours >= 1 else f"{hours * 60} мин."
            await callback.answer(f"✅ Первое уведомление за {time_text}")
            
            bot_logger.user_action(
                user_id=user.id,
                action="first_notification_time_changed",
                hours=hours
            )
            
            # Обновляем меню
            await show_settings_menu(callback.message, callback)
            
    except Exception as e:
        bot_logger.error(f"Error setting first notification time: {e}", user_id=user.id)
        await callback.answer("❌ Ошибка при изменении настроек")


@router.callback_query(F.data.startswith("set_second_notification:"))
async def set_second_notification_handler(callback: CallbackQuery):
    """Обработчик установки времени второго уведомления."""
    user = callback.from_user
    hours = int(callback.data.split(":")[1])
    
    try:
        async with get_db_session() as session:
            # Получаем пользователя
            db_user = await UserCRUD.get_by_telegram_id(session, user.id)
            if not db_user:
                await callback.answer("❌ Пользователь не найден")
                return
            
            # Обновляем настройки
            await NotificationSettingsCRUD.update(
                session, db_user.id, second_notification_hours=hours
            )
            
            time_text = f"{hours} ч." if hours >= 1 else f"{hours * 60} мин."
            await callback.answer(f"✅ Второе уведомление за {time_text}")
            
            bot_logger.user_action(
                user_id=user.id,
                action="second_notification_time_changed",
                hours=hours
            )
            
            # Обновляем меню
            await show_settings_menu(callback.message, callback)
            
    except Exception as e:
        bot_logger.error(f"Error setting second notification time: {e}", user_id=user.id)
        await callback.answer("❌ Ошибка при изменении настроек")


async def show_settings_menu(message: Message, callback: CallbackQuery = None):
    """Показывает меню настроек уведомлений."""
    user = callback.from_user if callback else message.from_user
    
    try:
        async with get_db_session() as session:
            # Получаем пользователя
            db_user = await UserCRUD.get_by_telegram_id(session, user.id)
            if not db_user:
                error_text = "❌ Пользователь не найден. Используйте /start для регистрации."
                if callback:
                    await callback.message.edit_text(error_text)
                    await callback.answer()
                else:
                    await message.answer(error_text)
                return
            
            # Получаем настройки уведомлений
            settings_obj, _ = await NotificationSettingsCRUD.get_or_create(session, db_user.id)
            
            # Формируем текст с текущими настройками
            status_emoji = "✅" if settings_obj.notifications_enabled else "❌"
            status_text = "включены" if settings_obj.notifications_enabled else "выключены"
            
            first_time_text = f"{settings_obj.first_notification_hours} ч." if settings_obj.first_notification_hours >= 1 else f"{settings_obj.first_notification_hours * 60} мин."
            second_time_text = f"{settings_obj.second_notification_hours} ч." if settings_obj.second_notification_hours >= 1 else f"{settings_obj.second_notification_hours * 60} мин."
            
            text = (
                "⚙️ <b>Настройки уведомлений</b>\n\n"
                f"{status_emoji} <b>Уведомления:</b> {status_text}\n"
                f"🔢 <b>Количество:</b> {settings_obj.notifications_count}\n"
                f"⏰ <b>Первое уведомление:</b> за {first_time_text}\n"
            )
            
            if settings_obj.notifications_count >= 2:
                text += f"⏰ <b>Второе уведомление:</b> за {second_time_text}\n"
            
            text += (
                f"🌍 <b>Часовой пояс:</b> {settings_obj.timezone}\n\n"
                "💡 Настройте уведомления под свои потребности:"
            )
            
            # Создаем клавиатуру
            keyboard = InlineKeyboardBuilder()
            
            # Кнопка включения/выключения уведомлений
            toggle_text = "❌ Выключить" if settings_obj.notifications_enabled else "✅ Включить"
            keyboard.button(text=toggle_text, callback_data="toggle_notifications")
            
            # Кнопки количества уведомлений
            keyboard.button(text="🔢 Количество", callback_data="show_count_options")
            
            # Кнопки времени уведомлений
            keyboard.button(text="⏰ Первое уведомление", callback_data="show_first_time_options")
            if settings_obj.notifications_count >= 2:
                keyboard.button(text="⏰ Второе уведомление", callback_data="show_second_time_options")
            
            # Кнопка возврата в главное меню
            keyboard.button(text="🏠 Главное меню", callback_data="main_menu")
            
            keyboard.adjust(1)
            
            if callback:
                await callback.message.edit_text(text, reply_markup=keyboard.as_markup())
                await callback.answer()
            else:
                await message.answer(text, reply_markup=keyboard.as_markup())
                
            bot_logger.user_action(user_id=user.id, action="settings_viewed")
        
    except Exception as e:
        bot_logger.error(f"Error in settings menu: {e}", user_id=user.id)
        error_text = "❌ Ошибка при загрузке настроек"
        if callback:
            await callback.message.edit_text(error_text)
            await callback.answer()
        else:
            await message.answer(error_text)


@router.callback_query(F.data == "show_count_options")
async def show_count_options_handler(callback: CallbackQuery):
    """Показывает опции количества уведомлений."""
    text = (
        "🔢 <b>Количество уведомлений</b>\n\n"
        "Выберите, сколько уведомлений вы хотите получать о каждом дедлайне:\n\n"
        "• <b>1 уведомление</b> - только основное напоминание\n"
        "• <b>2 уведомления</b> - основное + дополнительное напоминание"
    )
    
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="1️⃣ Одно уведомление", callback_data="set_notifications_count:1")
    keyboard.button(text="2️⃣ Два уведомления", callback_data="set_notifications_count:2")
    keyboard.button(text="◀️ Назад", callback_data="settings")
    keyboard.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=keyboard.as_markup())
    await callback.answer()


@router.callback_query(F.data == "show_first_time_options")
async def show_first_time_options_handler(callback: CallbackQuery):
    """Показывает опции времени первого уведомления."""
    text = (
        "⏰ <b>Время первого уведомления</b>\n\n"
        "За сколько времени до дедлайна отправлять первое уведомление:"
    )
    
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="🕐 За 1 час", callback_data="set_first_notification:1")
    keyboard.button(text="🕕 За 6 часов", callback_data="set_first_notification:6")
    keyboard.button(text="🕐 За 12 часов", callback_data="set_first_notification:12")
    keyboard.button(text="📅 За 1 день", callback_data="set_first_notification:24")
    keyboard.button(text="📅 За 2 дня", callback_data="set_first_notification:48")
    keyboard.button(text="📅 За 3 дня", callback_data="set_first_notification:72")
    keyboard.button(text="◀️ Назад", callback_data="settings")
    keyboard.adjust(2, 2, 2, 1)
    
    await callback.message.edit_text(text, reply_markup=keyboard.as_markup())
    await callback.answer()


@router.callback_query(F.data == "show_second_time_options")
async def show_second_time_options_handler(callback: CallbackQuery):
    """Показывает опции времени второго уведомления."""
    text = (
        "⏰ <b>Время второго уведомления</b>\n\n"
        "За сколько времени до дедлайна отправлять второе (финальное) уведомление:"
    )
    
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="⚡ За 30 минут", callback_data="set_second_notification:0.5")
    keyboard.button(text="🕐 За 1 час", callback_data="set_second_notification:1")
    keyboard.button(text="🕑 За 2 часа", callback_data="set_second_notification:2")
    keyboard.button(text="🕕 За 6 часов", callback_data="set_second_notification:6")
    keyboard.button(text="🕐 За 12 часов", callback_data="set_second_notification:12")
    keyboard.button(text="◀️ Назад", callback_data="settings")
    keyboard.adjust(2, 2, 1, 1)
    
    await callback.message.edit_text(text, reply_markup=keyboard.as_markup())
    await callback.answer()


def register_settings_handlers(dp):
    """Регистрирует хендлеры для настроек."""
    dp.include_router(router)