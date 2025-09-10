from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.bot.services.notification_service import notification_service
from src.core.database import db_manager
from src.utils import get_logger
import re

logger = get_logger()
router = Router()

class SettingsStates(StatesGroup):
    choosing_notification = State()
    setting_offset = State()

@router.message(Command("settings"))
@router.callback_query(F.data == "quick_settings")
async def cmd_settings(event: Message | CallbackQuery, db_user, state: FSMContext):
    """Обработчик команды /settings"""
    if isinstance(event, CallbackQuery):
        await event.answer()
        message = event.message
        edit_mode = True
    else:
        message = event
        edit_mode = False
    
    try:
        # Получаем текущие настройки пользователя
        settings = await notification_service.get_user_notification_settings(db_user.tg_user_id)
        
        text = "⚙️ <b>Настройки уведомлений</b>\n\n"
        
        if settings:
            status_text = "✅ Включены" if settings.is_active else "❌ Выключены"
            text += f"<b>Статус:</b> {status_text}\n\n"
            
            text += "<b>Текущие настройки:</b>\n"
            
            # Первое напоминание
            unit1_text = {
                'days': 'дн.',
                'hours': 'ч.'
            }.get(settings.reminder1_unit, settings.reminder1_unit)
            text += f"🔔 Напоминание 1: за {settings.reminder1_offset} {unit1_text}\n"
            
            # Второе напоминание
            unit2_text = {
                'days': 'дн.',
                'hours': 'ч.'
            }.get(settings.reminder2_unit, settings.reminder2_unit)
            text += f"🔔 Напоминание 2: за {settings.reminder2_offset} {unit2_text}\n"
        else:
            text += "<i>Настройки уведомлений не заданы</i>\n"
        
        text += "\n<b>Управление уведомлениями:</b>"
        
        builder = InlineKeyboardBuilder()
        
        builder.button(text="🔔 Напоминание 1", callback_data="setup_notification_1")
        builder.button(text="🔔 Напоминание 2", callback_data="setup_notification_2")
        
        if settings:
            if settings.is_active:
                builder.button(
                    text="🔕 Выключить уведомления",
                    callback_data="disable_notifications"
                )
            else:
                builder.button(
                    text="🔔 Включить уведомления",
                    callback_data="enable_notifications"
                )
            
        
        builder.button(text="🔙 Назад", callback_data="back_to_menu")
        builder.adjust(2, 1)
        
        if edit_mode:
            await message.edit_text(text, reply_markup=builder.as_markup())
        else:
            await message.answer(text, reply_markup=builder.as_markup())
        
    except Exception as e:
        logger.error(f"Ошибка в обработчике /settings: {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")

@router.callback_query(F.data.startswith("setup_notification_"))
async def callback_setup_notification(callback: CallbackQuery, db_user, state: FSMContext):
    """Обработчик настройки уведомления"""
    await callback.answer()
    
    try:
        notification_number = int(callback.data.split("_")[-1])
        
        text = f"🔔 <b>Настройка напоминания {notification_number}</b>\n\n"
        text += "Выберите, за сколько времени до дедлайна присылать напоминание:"
        
        builder = InlineKeyboardBuilder()
        
        presets = [
            (14, "days", "За 14 дней"),
            (7, "days", "За 7 дней"),
            (3, "days", "За 3 дня"),
            (1, "days", "За 1 день"),
            (12, "hours", "За 12 часов"),
            (6, "hours", "За 6 часов"),
        ]
        
        for offset_value, offset_unit, text_label in presets:
            builder.button(
                text=text_label,
                callback_data=f"set_notification_{notification_number}_{offset_value}_{offset_unit}"
            )
        
        builder.button(text="✏️ Свой вариант", callback_data=f"custom_notification_{notification_number}")
        builder.button(text="🔙 Назад к настройкам", callback_data="back_to_settings")
        builder.adjust(2)
        
        await state.update_data(notification_number=notification_number)
        await state.set_state(SettingsStates.choosing_notification)
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
        
    except (ValueError, IndexError):
        await callback.answer("Ошибка настройки уведомления", show_alert=True)

@router.callback_query(F.data.startswith("set_notification_"))
async def callback_set_notification(callback: CallbackQuery, db_user, state: FSMContext):
    """Обработчик установки уведомления"""
    await callback.answer()
    
    try:
        parts = callback.data.split("_")
        notification_number = int(parts[2])
        offset_value = int(parts[3])
        offset_unit = parts[4]
        
        success, message_text = await notification_service.set_user_notification(
            db_user.tg_user_id, notification_number, offset_value, offset_unit
        )
        
        if success:
            unit_text = {
                'days': 'дн.',
                'hours': 'ч.'
            }.get(offset_unit, offset_unit)
            
            await callback.answer(f"Уведомление настроено: за {offset_value} {unit_text}", show_alert=True)
            await state.clear()
            await cmd_settings(callback, db_user, state)
        else:
            await callback.answer(message_text, show_alert=True)
        
    except (ValueError, IndexError):
        await callback.answer("Ошибка установки уведомления", show_alert=True)

@router.callback_query(F.data == "enable_notifications")
async def callback_enable_notifications(callback: CallbackQuery, db_user):
    """Обработчик включения всех уведомлений"""
    await callback.answer()
    
    try:
        success, message_text = await notification_service.toggle_notifications(
            db_user.tg_user_id, True
        )
        
        await callback.answer(message_text, show_alert=True)
        
        if success:
            await cmd_settings(callback, db_user, None)
        
    except Exception as e:
        logger.error(f"Ошибка включения уведомлений: {e}")
        await callback.answer("Ошибка включения уведомлений", show_alert=True)

@router.callback_query(F.data == "disable_notifications")
async def callback_disable_notifications(callback: CallbackQuery, db_user):
    """Обработчик выключения всех уведомлений"""
    await callback.answer()
    
    try:
        success, message_text = await notification_service.toggle_notifications(
            db_user.tg_user_id, False
        )
        
        await callback.answer(message_text, show_alert=True)
        
        if success:
            await cmd_settings(callback, db_user, None)
        
    except Exception as e:
        logger.error(f"Ошибка выключения уведомлений: {e}")
        await callback.answer("Ошибка выключения уведомлений", show_alert=True)


@router.callback_query(F.data == "back_to_settings")
async def callback_back_to_settings(callback: CallbackQuery, db_user, state: FSMContext):
    """Возврат к настройкам"""
    await callback.answer()
    await state.clear()
    await cmd_settings(callback, db_user, state)

@router.callback_query(F.data.startswith("custom_notification_"))
async def callback_custom_notification(callback: CallbackQuery, db_user, state: FSMContext):
    """Обработчик кастомного уведомления"""
    await callback.answer()
    
    try:
        notification_number = int(callback.data.split("_")[-1])
        
        text = f"✏️ <b>Настройка уведомления {notification_number}</b>\n\n"
        text += "Отправьте сообщение в формате:\n"
        text += "<code>число единица</code>\n\n"
        text += "<b>Примеры:</b>\n"
        text += "• <code>2 дня</code> или <code>2 дн</code>\n"
        text += "• <code>6 часов</code> или <code>6 ч</code>\n\n"
        text += "Или нажмите 'Отмена' для возврата."
        
        builder = InlineKeyboardBuilder()
        builder.button(text="❌ Отмена", callback_data="back_to_settings")
        
        await state.update_data(notification_number=notification_number)
        await state.set_state(SettingsStates.setting_offset)
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
        
    except (ValueError, IndexError):
        await callback.answer("Ошибка настройки", show_alert=True)

@router.message(SettingsStates.setting_offset)
async def process_custom_offset(message: Message, db_user, state: FSMContext):
    """Обработка кастомного времени уведомления"""
    try:
        data = await state.get_data()
        notification_number = data.get('notification_number')
        
        if not notification_number:
            await message.answer("Ошибка: номер уведомления не найден")
            await state.clear()
            return
        
        text = message.text.strip().lower()
        
        patterns = [
            (r'(\d+)\s*(?:дн|день|дня|дней|days?)', 'days'),
            (r'(\d+)\s*(?:ч|час|часа|часов|hours?)', 'hours')
        ]
        
        offset_value = None
        offset_unit = None
        
        for pattern, unit in patterns:
            match = re.search(pattern, text)
            if match:
                offset_value = int(match.group(1))
                offset_unit = unit
                break
        
        if not offset_value or not offset_unit:
            await message.answer(
                "❌ Не удалось распознать формат.\n"
                "Используйте формат: <code>число единица</code>\n"
                "Например: <code>2 дня</code>, <code>6 часов</code>"
            )
            return
        
        # Проверяем минимальное время (1 час)
        total_hours = 0
        if offset_unit == 'hours':
            total_hours = offset_value
        elif offset_unit == 'days':
            total_hours = offset_value * 24
        
        if total_hours < 1:
            await message.answer(
                "❌ Минимальное время уведомления - 1 час\n"
            )
            return
        
        # Проверяем разумные пределы
        if offset_unit == 'days' and offset_value > 30:
            await message.answer("❌ Максимум 30 дней")
            return
        elif offset_unit == 'hours' and offset_value > 24 * 7:
            await message.answer("❌ Максимум 168 часов (неделя)")
            return
        
        # Устанавливаем уведомление
        success, message_text = await notification_service.set_user_notification(
            db_user.tg_user_id, notification_number, offset_value, offset_unit
        )
        
        if success:
            unit_text = {
                'days': 'дн.',
                'hours': 'ч.'
            }.get(offset_unit, offset_unit)
            
            await message.answer(f"✅ Уведомление настроено: за {offset_value} {unit_text}")
            await state.clear()
            
            # Показываем обновленные настройки
            await cmd_settings(message, db_user, state)
        else:
            await message.answer(f"❌ {message_text}")
        
    except Exception as e:
        logger.error(f"Ошибка обработки кастомного времени: {e}")
        await message.answer("Произошла ошибка. Попробуйте еще раз.")

def register_settings_handlers(dp):
    """Регистрация handlers для настроек"""
    dp.include_router(router)