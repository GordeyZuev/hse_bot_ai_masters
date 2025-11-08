import re

from aiogram import F, Router
from aiogram.filters import Command, and_f
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.bot.services.notification_service import notification_service
from src.bot.texts import (
    ERROR_COMMAND_SETTINGS,
    ERROR_TRY_AGAIN,
    NOTIFICATION_MAX_DAYS,
    NOTIFICATION_MAX_HOURS,
    NOTIFICATION_MIN_TIME,
    NOTIFICATION_SET,
    NOTIFICATION_SETUP_TEXT,
    SLEEP_INVALID_END_TIME,
    SLEEP_INVALID_FORMAT,
    SLEEP_INVALID_START_TIME,
    SLEEP_SAME_TIMES,
    SLEEP_SETTINGS_CONFIGURED,
    SLEEP_SETTINGS_NOT_CONFIGURED,
    SLEEP_SETTINGS_TITLE,
    SLEEP_SETUP_INSTRUCTIONS,
    TIMEZONE_REQUEST_LOCATION_TEXT,
    TIMEZONE_SETUP_TEXT,
    TIMEZONE_UPDATED_TEXT,
)
from src.core.database import db_manager
from src.utils import get_logger, safe_edit_message
from src.utils.notification_text import build_custom_offset_prompt, parse_offset_text


logger = get_logger()
router = Router()


class SettingsStates(StatesGroup):
    choosing_notification = State()
    setting_offset = State()
    waiting_for_location = State()
    setting_sleep_time = State()


@router.message(and_f(Command("settings"), F.chat.type == "private"))
@router.callback_query(F.data == "quick_settings")
async def cmd_settings(event: Message | CallbackQuery, db_user, state: FSMContext):  # noqa: ARG001
    """Обработчик команды /settings"""
    if isinstance(event, CallbackQuery):
        await event.answer()
        message = event.message
        edit_mode = True
    else:
        message = event
        edit_mode = False

    try:
        fresh_user = await db_manager.get_user_by_id(db_user.tg_user_id)
        user_for_view = fresh_user or db_user
        settings = await notification_service.get_user_notification_settings(
            db_user.tg_user_id
        )

        text = "⚙️ <b>Настройки уведомлений</b>\n\n"

        if settings:
            # Уведомления о дедлайнах
            deadline_status = "✅ Включены" if settings.is_active else "❌ Отключены"
            text += f"Уведомления о дедлайнах {deadline_status}\n"

            # Уведомления об обновлениях
            update_status = "✅ Включены" if settings.enable_deadline_update_notifications else "❌ Отключены"
            text += f"Уведомления об обновлениях {update_status}\n\n"

            unit1_text = {"days": "дн.", "hours": "ч."}.get(
                settings.reminder1_unit, settings.reminder1_unit
            )
            text += f"🔔 Напоминание 1: за {settings.reminder1_offset} {unit1_text}\n"

            unit2_text = {"days": "дн.", "hours": "ч."}.get(
                settings.reminder2_unit, settings.reminder2_unit
            )
            text += f"🔔 Напоминание 2: за {settings.reminder2_offset} {unit2_text}\n\n"

            # Показываем время сна, если установлено
            if settings.sleep_start_time and settings.sleep_end_time:
                sleep_start_str = settings.sleep_start_time.strftime("%H:%M")
                sleep_end_str = settings.sleep_end_time.strftime("%H:%M")
                text += f"⏰ Режим сна: {sleep_start_str} - {sleep_end_str}\n"
            else:
                text += "⏰ Режим сна: не настроен\n"
        else:
            text += "<i>Настройки уведомлений не заданы</i>\n"

        from src.utils.time import format_offset_from_moscow_label

        msk_label = format_offset_from_moscow_label(user_for_view.timezone)
        text += f"\nЧасовой пояс: {user_for_view.timezone} ({msk_label})"

        builder = InlineKeyboardBuilder()

        builder.button(text="🔔 Напоминание 1", callback_data="setup_notification_1")
        builder.button(text="🔔 Напоминание 2", callback_data="setup_notification_2")

        # Вторая строка: Часовой пояс и Режим сна
        builder.button(text="🌍 Часовой пояс", callback_data="choose_timezone")
        builder.button(text="⏰ Режим сна", callback_data="sleep_settings")

        if settings:
            if settings.is_active:
                builder.button(
                    text="🔕 Дедлайны - отключить уведомления",
                    callback_data="disable_notifications",
                )
            else:
                builder.button(
                    text="🔔 Дедлайны - включить уведомления",
                    callback_data="enable_notifications"
                )

        if settings:
            if settings.enable_deadline_update_notifications:
                builder.button(
                    text="🔕 Изменения - отключить уведомления",
                    callback_data="toggle_update_notifications",
                )
            else:
                builder.button(
                    text="🔔 Изменения - включить уведомления",
                    callback_data="toggle_update_notifications",
                )

        builder.button(text="🔙 Назад", callback_data="back_to_menu")

        builder.adjust(2, 2, 1, 1, 1)

        if edit_mode:
            await safe_edit_message(message, text, reply_markup=builder.as_markup())
        else:
            await message.answer(text, reply_markup=builder.as_markup())

    except Exception as e:
        user_id = message.from_user.id if message.from_user else 0
        logger.error(f"(U) {user_id} - команда /settings: {e}")
        await message.answer(ERROR_COMMAND_SETTINGS)


@router.callback_query(F.data == "choose_timezone")
async def callback_choose_timezone(callback: CallbackQuery, db_user, state: FSMContext):  # noqa: ARG001
    """Начало выбора часового пояса: предлагаем отправить геолокацию"""
    await callback.answer()
    try:
        text = TIMEZONE_SETUP_TEXT.format(timezone=db_user.timezone)
        builder = InlineKeyboardBuilder()
        builder.button(
            text="📍 Отправить местоположение", callback_data="request_location"
        )
        builder.button(text="🔙 К настройкам", callback_data="back_to_settings")
        builder.adjust(1, 1)
        await safe_edit_message(callback.message, text, reply_markup=builder.as_markup())
    except Exception as e:
        logger.error(f"Ошибка запуска выбора часового пояса: {e}")
        await callback.answer("Ошибка", show_alert=True)


@router.callback_query(F.data == "request_location")
async def callback_request_location(
    callback: CallbackQuery, db_user, state: FSMContext  # noqa: ARG001
):
    """Запрос местоположения для определения часового пояса"""
    await callback.answer()
    try:
        await state.set_state(SettingsStates.waiting_for_location)
        text = TIMEZONE_REQUEST_LOCATION_TEXT
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 Назад", callback_data="choose_timezone")
        await safe_edit_message(callback.message, text, reply_markup=builder.as_markup())
    except Exception as e:
        logger.error(f"Ошибка запроса местоположения: {e}")
        await callback.answer("Ошибка", show_alert=True)


@router.message(SettingsStates.waiting_for_location)
async def process_location(message: Message, db_user, state: FSMContext):
    """Обработка полученной геолокации"""
    try:
        if not message.location:
            await message.answer("❌ Пожалуйста, отправьте ваше местоположение.")
            return

        latitude = message.location.latitude
        longitude = message.location.longitude

        from src.utils.time import get_timezone_from_location_with_city

        timezone_name, city_name = get_timezone_from_location_with_city(
            latitude, longitude
        )

        updated = await db_manager.update_user_timezone(
            db_user.tg_user_id, timezone_name
        )

        if updated:
            from src.utils.time import format_offset_from_moscow_label

            msk_label = format_offset_from_moscow_label(timezone_name)

            await message.answer(
                TIMEZONE_UPDATED_TEXT.format(
                    city_name=city_name,
                    timezone=timezone_name,
                    msk_label=msk_label,
                )
            )
            await state.clear()
            await cmd_settings(message, db_user, state)
        else:
            await message.answer("❌ Не удалось обновить часовой пояс")

    except Exception as e:
        logger.error(f"Ошибка обработки геолокации: {e}")
        await message.answer(
            "❌ Произошла ошибка при обработке местоположения. Попробуйте ещё раз."
        )


@router.callback_query(F.data.startswith("setup_notification_"))
async def callback_setup_notification(
    callback: CallbackQuery, db_user, state: FSMContext  # noqa: ARG001
):
    """Обработчик настройки уведомления"""
    await callback.answer()

    try:
        notification_number = int(callback.data.split("_")[-1])

        text = NOTIFICATION_SETUP_TEXT.format(notification_number=notification_number)

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
                callback_data=f"set_notification_{notification_number}_{offset_value}_{offset_unit}",
            )

        builder.button(
            text="✏️ Свой вариант",
            callback_data=f"custom_notification_{notification_number}",
        )
        builder.button(text="🔙 Назад к настройкам", callback_data="back_to_settings")
        builder.adjust(2)

        await state.update_data(notification_number=notification_number)
        await state.set_state(SettingsStates.choosing_notification)
        await safe_edit_message(callback.message, text, reply_markup=builder.as_markup())

    except (ValueError, IndexError):
        await callback.answer("Ошибка настройки уведомления", show_alert=True)


@router.callback_query(F.data.startswith("set_notification_"))
async def callback_set_notification(
    callback: CallbackQuery, db_user, state: FSMContext
):
    """Обработчик установки уведомления"""
    try:
        parts = callback.data.split("_")
        notification_number = int(parts[2])
        offset_value = int(parts[3])
        offset_unit = parts[4]

        success, message_text = await notification_service.set_user_notification(
            db_user.tg_user_id, notification_number, offset_value, offset_unit
        )

        if success:
            unit_text = {"days": "дн.", "hours": "ч."}.get(offset_unit, offset_unit)

            await callback.answer(
                f"Уведомление настроено: за {offset_value} {unit_text}", show_alert=True
            )
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
        user_id = callback.from_user.id if callback.from_user else 0
        logger.error(f"(U) {user_id} - включение уведомлений: {e}")
        await callback.answer("Ошибка включения уведомлений", show_alert=True)


@router.callback_query(F.data == "disable_notifications")
async def callback_disable_notifications(callback: CallbackQuery, db_user):
    """Обработчик отключения всех уведомлений"""
    await callback.answer()

    try:
        success, message_text = await notification_service.toggle_notifications(
            db_user.tg_user_id, False
        )

        await callback.answer(message_text, show_alert=True)

        if success:
            await cmd_settings(callback, db_user, None)

    except Exception as e:
        logger.error(f"Ошибка отключения уведомлений: {e}")
        await callback.answer("Ошибка отключения уведомлений", show_alert=True)


@router.callback_query(F.data == "back_to_settings")
async def callback_back_to_settings(
    callback: CallbackQuery, db_user, state: FSMContext
):
    """Возврат к настройкам"""
    await callback.answer()
    await state.clear()
    await cmd_settings(callback, db_user, state)


@router.callback_query(F.data.startswith("custom_notification_"))
async def callback_custom_notification(
    callback: CallbackQuery, db_user, state: FSMContext  # noqa: ARG001
):
    """Обработчик кастомного уведомления"""
    await callback.answer()

    try:
        notification_number = int(callback.data.split("_")[-1])

        text, buttons = build_custom_offset_prompt(notification_number, "back_to_settings")

        builder = InlineKeyboardBuilder()
        for btn_text, cb_data in buttons:
            builder.button(text=btn_text, callback_data=cb_data)

        await state.update_data(notification_number=notification_number)
        await state.set_state(SettingsStates.setting_offset)
        await safe_edit_message(callback.message, text, reply_markup=builder.as_markup())

    except (ValueError, IndexError):
        await callback.answer("Ошибка настройки", show_alert=True)


@router.message(SettingsStates.setting_offset)
async def process_custom_offset(message: Message, db_user, state: FSMContext):
    """Обработка кастомного времени уведомления"""
    try:
        data = await state.get_data()
        notification_number = data.get("notification_number")

        if not notification_number:
            await message.answer("Ошибка: номер уведомления не найден")
            await state.clear()
            return

        value, unit, error = parse_offset_text(message.text)
        if error:
            await message.answer(error)
            return
        offset_value, offset_unit = value, unit

        total_hours = 0
        if offset_unit == "hours":
            total_hours = offset_value
        elif offset_unit == "days":
            total_hours = offset_value * 24

        if total_hours < 1:
            await message.answer(NOTIFICATION_MIN_TIME)
            return

        if offset_unit == "days" and offset_value > 30:
            await message.answer(NOTIFICATION_MAX_DAYS)
            return
        elif offset_unit == "hours" and offset_value > 24 * 7:
            await message.answer(NOTIFICATION_MAX_HOURS)
            return

        success, message_text = await notification_service.set_user_notification(
            db_user.tg_user_id, notification_number, offset_value, offset_unit
        )

        if success:
            unit_text = {"days": "дн.", "hours": "ч."}.get(offset_unit, offset_unit)

            await message.answer(
                NOTIFICATION_SET.format(offset_value=offset_value, unit_text=unit_text)
            )
            await state.clear()

            await cmd_settings(message, db_user, state)
        else:
            await message.answer(f"❌ {message_text}")

    except Exception as e:
        logger.error(f"Ошибка обработки кастомного времени: {e}")
        await message.answer("Произошла ошибка. Попробуйте еще раз.")


@router.callback_query(F.data == "sleep_settings")
async def callback_sleep_settings(callback: CallbackQuery, db_user):
    """Обработчик экрана настроек режима сна"""
    await callback.answer()
    try:
        settings = await notification_service.get_user_notification_settings(
            db_user.tg_user_id
        )

        if settings and settings.sleep_start_time and settings.sleep_end_time:
            sleep_start_str = settings.sleep_start_time.strftime("%H:%M")
            sleep_end_str = settings.sleep_end_time.strftime("%H:%M")
            text = SLEEP_SETTINGS_CONFIGURED.format(
                start_time=sleep_start_str, end_time=sleep_end_str
            )
        else:
            text = SLEEP_SETTINGS_NOT_CONFIGURED

        builder = InlineKeyboardBuilder()
        builder.button(text="⚙️ Настроить", callback_data="setup_sleep_time")
        if settings and settings.sleep_start_time and settings.sleep_end_time:
            builder.button(text="🗑️ Сбросить", callback_data="clear_sleep_time")
        builder.button(text="🔙 К настройкам", callback_data="back_to_settings")
        builder.adjust(2, 1)

        await safe_edit_message(callback.message, text, reply_markup=builder.as_markup())
    except Exception as e:
        logger.error(f"Ошибка открытия настроек сна: {e}")
        await callback.answer("Ошибка", show_alert=True)


@router.callback_query(F.data == "setup_sleep_time")
async def callback_setup_sleep_time(
    callback: CallbackQuery, db_user, state: FSMContext  # noqa: ARG001
):
    """Обработчик начала настройки времени сна"""
    await callback.answer()
    try:
        text = SLEEP_SETUP_INSTRUCTIONS
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 К режиму сна", callback_data="sleep_settings")
        await state.set_state(SettingsStates.setting_sleep_time)
        await safe_edit_message(callback.message, text, reply_markup=builder.as_markup())
    except Exception as e:
        logger.error(f"Ошибка настройки времени сна: {e}")
        await callback.answer("Ошибка", show_alert=True)


@router.message(SettingsStates.setting_sleep_time)
async def process_sleep_time(message: Message, db_user, state: FSMContext):
    """Обработка ввода времени сна"""
    try:
        input_text = message.text.strip()

        pattern = r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})"
        match = re.match(pattern, input_text)

        if not match:
            await message.answer(SLEEP_INVALID_FORMAT, parse_mode="HTML")
            return

        try:
            start_hour = int(match.group(1))
            start_minute = int(match.group(2))
            end_hour = int(match.group(3))
            end_minute = int(match.group(4))

            if not (0 <= start_hour <= 23 and 0 <= start_minute <= 59):
                await message.answer(SLEEP_INVALID_START_TIME)
                return

            if not (0 <= end_hour <= 23 and 0 <= end_minute <= 59):
                await message.answer(SLEEP_INVALID_END_TIME)
                return

            from datetime import time
            sleep_start = time(start_hour, start_minute)
            sleep_end = time(end_hour, end_minute)

            if sleep_start == sleep_end:
                await message.answer(SLEEP_SAME_TIMES)
                return

            success, message_text = await notification_service.set_sleep_time(
                db_user.tg_user_id, sleep_start, sleep_end
            )

            if success:
                start_str = sleep_start.strftime("%H:%M")
                end_str = sleep_end.strftime("%H:%M")
                await state.clear()

                await notification_service.get_user_notification_settings(
                    db_user.tg_user_id
                )

                text = SLEEP_SETTINGS_CONFIGURED.format(
                    start_time=start_str, end_time=end_str
                )

                builder = InlineKeyboardBuilder()
                builder.button(text="⚙️ Настроить", callback_data="setup_sleep_time")
                builder.button(text="🗑️ Сбросить", callback_data="clear_sleep_time")
                builder.button(text="🔙 К настройкам", callback_data="back_to_settings")
                builder.adjust(2, 1)

                await message.answer(text, reply_markup=builder.as_markup())
            else:
                await message.answer(f"❌ {message_text}")

        except ValueError as e:
            await message.answer(f"❌ Ошибка обработки времени: {e}")

    except Exception as e:
        logger.error(f"Ошибка обработки времени сна: {e}")
        await message.answer("Произошла ошибка. Попробуйте еще раз.")


@router.callback_query(F.data == "clear_sleep_time")
async def callback_clear_sleep_time(callback: CallbackQuery, db_user):
    """Обработчик сброса времени сна"""
    await callback.answer()
    try:
        success, message_text = await notification_service.set_sleep_time(
            db_user.tg_user_id, None, None
        )

        await callback.answer(message_text, show_alert=True)

        if success:
            await callback_sleep_settings(callback, db_user)

    except Exception as e:
        logger.error(f"Ошибка сброса времени сна: {e}")
        await callback.answer("Ошибка сброса времени сна", show_alert=True)


@router.callback_query(F.data == "toggle_update_notifications")
async def callback_toggle_update_notifications(callback: CallbackQuery, db_user):
    """Обработчик переключения уведомлений об обновлениях"""
    await callback.answer()
    try:
        settings = await notification_service.get_user_notification_settings(
            db_user.tg_user_id
        )
        if not settings:
            await callback.answer("Ошибка: настройки не найдены", show_alert=True)
            return

        new_value = not settings.enable_deadline_update_notifications
        success, message_text = await notification_service.toggle_deadline_update_notifications(
            db_user.tg_user_id, new_value
        )

        await callback.answer(message_text, show_alert=True)

        if success:
            await cmd_settings(callback, db_user, None)

    except Exception as e:
        logger.error(f"Ошибка переключения уведомлений об обновлениях: {e}")
        await callback.answer("Ошибка", show_alert=True)


def register_settings_handlers(dp):
    """Регистрация handlers для настроек"""
    dp.include_router(router)
