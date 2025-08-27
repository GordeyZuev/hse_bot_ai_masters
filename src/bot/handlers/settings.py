from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.bot.services.notification_service import notification_service
from src.utils import get_logger

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
        notifications = await notification_service.get_user_notifications(db_user.tg_user_id)
        
        text = "⚙️ <b>Настройки уведомлений</b>\n\n"
        
        if notifications:
            text += "<b>Текущие настройки:</b>\n"
            for notif in notifications:
                status = "✅" if notif.is_enabled else "❌"
                unit_text = {
                    'days': 'дн.',
                    'hours': 'ч.',
                    'minutes': 'мин.'
                }.get(notif.offset_unit, notif.offset_unit)
                
                text += f"{status} Уведомление {notif.notification_number}: за {notif.offset_value} {unit_text}\n"
        else:
            text += "<i>Настройки уведомлений не заданы</i>\n"
        
        text += "\n<b>Управление уведомлениями:</b>"
        
        # Создаем клавиатуру
        builder = InlineKeyboardBuilder()
        
        # Кнопки управления уведомлениями
        builder.button(text="🔔 Уведомление 1", callback_data="setup_notification_1")
        builder.button(text="🔔 Уведомление 2", callback_data="setup_notification_2")
        
        if notifications:
            # Кнопки включения/выключения
            for notif in notifications:
                if notif.is_enabled:
                    builder.button(
                        text=f"🔕 Выключить уведомление {notif.notification_number}",
                        callback_data=f"disable_notification_{notif.notification_number}"
                    )
                else:
                    builder.button(
                        text=f"🔔 Включить уведомление {notif.notification_number}",
                        callback_data=f"enable_notification_{notif.notification_number}"
                    )
        
        builder.button(text="🗑 Сбросить все настройки", callback_data="reset_notifications")
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
        
        text = f"🔔 <b>Настройка уведомления {notification_number}</b>\n\n"
        text += "Выберите, за сколько времени до дедлайна присылать уведомление:"
        
        builder = InlineKeyboardBuilder()
        
        # Предустановленные варианты
        presets = [
            (1, "days", "За 1 день"),
            (3, "days", "За 3 дня"),
            (7, "days", "За неделю"),
            (12, "hours", "За 12 часов"),
            (6, "hours", "За 6 часов"),
            (2, "hours", "За 2 часа"),
            (30, "minutes", "За 30 минут")
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
                'hours': 'ч.',
                'minutes': 'мин.'
            }.get(offset_unit, offset_unit)
            
            await callback.answer(f"Уведомление настроено: за {offset_value} {unit_text}", show_alert=True)
            await state.clear()
            # Возвращаемся к настройкам
            await cmd_settings(callback, db_user, state)
        else:
            await callback.answer(message_text, show_alert=True)
        
    except (ValueError, IndexError):
        await callback.answer("Ошибка установки уведомления", show_alert=True)

@router.callback_query(F.data.startswith("enable_notification_"))
async def callback_enable_notification(callback: CallbackQuery, db_user):
    """Обработчик включения уведомления"""
    await callback.answer()
    
    try:
        notification_number = int(callback.data.split("_")[-1])
        success, message_text = await notification_service.toggle_notification(
            db_user.tg_user_id, notification_number, True
        )
        
        await callback.answer(message_text, show_alert=True)
        
        if success:
            # Обновляем интерфейс
            await cmd_settings(callback, db_user, None)
        
    except (ValueError, IndexError):
        await callback.answer("Ошибка включения уведомления", show_alert=True)

@router.callback_query(F.data.startswith("disable_notification_"))
async def callback_disable_notification(callback: CallbackQuery, db_user):
    """Обработчик выключения уведомления"""
    await callback.answer()
    
    try:
        notification_number = int(callback.data.split("_")[-1])
        success, message_text = await notification_service.toggle_notification(
            db_user.tg_user_id, notification_number, False
        )
        
        await callback.answer(message_text, show_alert=True)
        
        if success:
            # Обновляем интерфейс
            await cmd_settings(callback, db_user, None)
        
    except (ValueError, IndexError):
        await callback.answer("Ошибка выключения уведомления", show_alert=True)

@router.callback_query(F.data == "reset_notifications")
async def callback_reset_notifications(callback: CallbackQuery, db_user):
    """Обработчик сброса всех настроек"""
    await callback.answer()
    
    try:
        success, message_text = await notification_service.reset_user_notifications(db_user.tg_user_id)
        await callback.answer(message_text, show_alert=True)
        
        if success:
            # Обновляем интерфейс
            await cmd_settings(callback, db_user, None)
        
    except Exception as e:
        logger.error(f"Ошибка сброса настроек: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)

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
        text += "• <code>6 часов</code> или <code>6 ч</code>\n"
        text += "• <code>30 минут</code> или <code>30 мин</code>\n\n"
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
        
        # Парсим введенный текст
        text = message.text.strip().lower()
        
        # Регулярные выражения для парсинга
        import re
        
        # Паттерны для разных единиц времени
        patterns = [
            (r'(\d+)\s*(?:дн|день|дня|дней|days?)', 'days'),
            (r'(\d+)\s*(?:ч|час|часа|часов|hours?)', 'hours'),
            (r'(\d+)\s*(?:мин|минут|минуты|minutes?)', 'minutes')
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
                "Например: <code>2 дня</code>, <code>6 часов</code>, <code>30 минут</code>"
            )
            return
        
        # Проверяем разумные пределы
        if offset_unit == 'days' and offset_value > 30:
            await message.answer("❌ Максимум 30 дней")
            return
        elif offset_unit == 'hours' and offset_value > 24 * 7:
            await message.answer("❌ Максимум 168 часов (неделя)")
            return
        elif offset_unit == 'minutes' and offset_value > 60 * 24:
            await message.answer("❌ Максимум 1440 минут (сутки)")
            return
        
        # Устанавливаем уведомление
        success, message_text = await notification_service.set_user_notification(
            db_user.tg_user_id, notification_number, offset_value, offset_unit
        )
        
        if success:
            unit_text = {
                'days': 'дн.',
                'hours': 'ч.',
                'minutes': 'мин.'
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