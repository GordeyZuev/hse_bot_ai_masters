import re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.bot.services.deadline_service import deadline_service
from src.utils import get_logger

logger = get_logger()
router = Router()

@router.message(Command("deadlines"))
async def cmd_deadlines(message: Message, db_user):
    """Обработчик команды /deadlines [N]"""
    try:
        # Парсим количество дней из команды
        days = 15  # по умолчанию
        
        # Извлекаем число из текста команды
        text = message.text.strip()
        match = re.search(r'/deadlines\s+(\d+)', text)
        if match:
            try:
                days = int(match.group(1))
                # Ограничиваем разумными пределами
                if days < 1:
                    days = 1
                elif days > 365:
                    days = 365
            except ValueError:
                days = 15
        
        await send_deadlines_list(message, db_user, days)
        
    except Exception as e:
        logger.error(f"Ошибка в обработчике /deadlines: {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")

@router.callback_query(F.data == "quick_deadlines")
async def callback_deadlines(callback: CallbackQuery, db_user):
    """Обработчик кнопки быстрого доступа к дедлайнам"""
    await callback.answer()
    await send_deadlines_list(callback.message, db_user, 15)

@router.callback_query(F.data.startswith("deadlines_"))
async def callback_deadlines_period(callback: CallbackQuery, db_user):
    """Обработчик выбора периода дедлайнов"""
    await callback.answer()
    
    try:
        days = int(callback.data.split("_")[1])
        await send_deadlines_list(callback.message, db_user, days, edit=True)
    except (ValueError, IndexError):
        await callback.answer("Ошибка выбора периода", show_alert=True)

async def send_deadlines_list(message: Message, db_user, days: int, edit: bool = False):
    """Отправка списка дедлайнов"""
    try:
        # Получаем дедлайны пользователя
        deadlines_data = await deadline_service.get_user_deadlines(db_user.tg_user_id, days)
        
        # Форматируем сообщение
        text = deadline_service.format_deadlines_list(deadlines_data, days)
        
        # Создаем клавиатуру с периодами и действиями
        builder = InlineKeyboardBuilder()
        
        # Кнопки выбора периода
        periods = [
            (7, "7 дней"),
            (15, "15 дней"),
            (30, "30 дней")
        ]
        
        for period_days, period_text in periods:
            if period_days == days:
                button_text = f"✅ {period_text}"
                callback_data = f"current_{period_days}"
            else:
                button_text = period_text
                callback_data = f"deadlines_{period_days}"
            
            builder.button(text=button_text, callback_data=callback_data)
        
        builder.adjust(3)  # 3 кнопки в ряд
        
        # Дополнительные действия если есть дедлайны
        if not deadlines_data:
            builder.row()
            builder.button(text="📚 Подписки", callback_data="quick_sub")
        
        # Кнопка назад
        builder.row()
        builder.button(text="🔙 Назад", callback_data="back_to_menu")
        
        if edit:
            await message.edit_text(text, reply_markup=builder.as_markup())
        else:
            await message.answer(text, reply_markup=builder.as_markup())
        
        logger.info(f"Пользователь {db_user.tg_user_id} запросил дедлайны на {days} дней")
        
    except Exception as e:
        logger.error(f"Ошибка отправки списка дедлайнов: {e}")
        error_text = "Произошла ошибка при получении дедлайнов. Попробуйте позже."
        
        if edit:
            await message.edit_text(error_text)
        else:
            await message.answer(error_text)

@router.callback_query(F.data.startswith("deadlines_detailed_"))
async def callback_detailed_deadlines(callback: CallbackQuery, db_user):
    """Обработчик подробного просмотра дедлайнов"""
    await callback.answer()
    
    try:
        days = int(callback.data.split("_")[2])
        deadlines_data = await deadline_service.get_user_deadlines(db_user.tg_user_id, days)
        
        if not deadlines_data:
            await callback.answer("Дедлайны не найдены", show_alert=True)
            return
        
        # Создаем подробное сообщение со всеми дедлайнами
        detailed_text = f"📋 <b>Подробные дедлайны на {days} дней</b>\n\n"
        
        for i, data in enumerate(deadlines_data, 1):
            detailed_text += f"<b>{i}. {data['subject'].name}</b>\n"
            detailed_text += f"📝 <b>{data['deadline'].hw_name}</b>\n\n"
            
            # Текущее время для проверки актуальности
            from datetime import datetime
            import pytz
            moscow_tz = pytz.timezone('Europe/Moscow')
            now = datetime.now(moscow_tz)
            
            # Показываем все дедлайны с отметками о прошедших
            if data['deadline'].soft_deadline_ts:
                soft_moscow = data['deadline'].soft_deadline_ts.astimezone(moscow_tz)
                soft_date = soft_moscow.strftime("%d.%m.%Y %H:%M МСК")
                
                if data['deadline'].soft_deadline_ts >= now:
                    detailed_text += f"🟡 <b>Мягкий:</b> {soft_date}\n"
                else:
                    detailed_text += f"🟡 <b>Мягкий:</b> {soft_date} <i>(прошел)</i>\n"
            
            if data['deadline'].hard_deadline_ts:
                hard_moscow = data['deadline'].hard_deadline_ts.astimezone(moscow_tz)
                hard_date = hard_moscow.strftime("%d.%m.%Y %H:%M МСК")
                
                if data['deadline'].hard_deadline_ts >= now:
                    detailed_text += f"🔴 <b>Жесткий:</b> {hard_date}\n"
                else:
                    detailed_text += f"🔴 <b>Жесткий:</b> {hard_date} <i>(прошел)</i>\n"
            
            # Время до ближайшего дедлайна
            if 'nearest_deadline' in data:
                time_left = data['nearest_deadline'] - now
                days_left = time_left.days
                hours_left = time_left.seconds // 3600
                deadline_name = "мягкого" if data['deadline_type'] == "soft" else "жесткого"
                
                if days_left > 0:
                    detailed_text += f"⏰ <b>До {deadline_name}:</b> {days_left} дн. {hours_left} ч.\n"
                elif hours_left > 0:
                    detailed_text += f"⏰ <b>До {deadline_name}:</b> {hours_left} ч.\n"
                else:
                    detailed_text += f"🚨 <b>{deadline_name.capitalize()} дедлайн сегодня!</b>\n"
            
            # Ссылка и комментарий
            if data['deadline'].source_link and data['deadline'].source_link.strip():
                detailed_text += f"🔗 <a href='{data['deadline'].source_link}'>Ссылка на задание</a>\n"
            
            if data['deadline'].note and data['deadline'].note.strip():
                detailed_text += f"💬 <i>{data['deadline'].note}</i>\n"
            
            detailed_text += "\n" + "─" * 30 + "\n\n"
        
        # Создаем кнопку возврата
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 Назад к списку", callback_data=f"deadlines_{days}")
        
        # Отправляем подробное сообщение
        await callback.message.edit_text(
            detailed_text,
            reply_markup=builder.as_markup(),
            disable_web_page_preview=True
        )
        
    except (ValueError, IndexError):
        await callback.answer("Ошибка получения подробной информации", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка подробного просмотра дедлайнов: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)

@router.callback_query(F.data.startswith("current_"))
async def callback_current_period(callback: CallbackQuery):
    """Обработчик нажатия на текущий период"""
    await callback.answer("Уже выбран этот период", show_alert=False)

def register_deadline_handlers(dp):
    """Регистрация handlers для дедлайнов"""
    dp.include_router(router)