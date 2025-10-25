import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.bot.services.deadline_service import deadline_service
from src.utils import get_logger


logger = get_logger()
router = Router()


@router.message(Command("deadlines"))
async def cmd_deadlines(message: Message, db_user):
    """Обработчик команды /deadlines [N]"""
    try:
        days = 15

        text = message.text.strip()
        match = re.search(r"/deadlines\s+(\d+)", text)
        if match:
            try:
                days = int(match.group(1))
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
    await send_deadlines_list(callback.message, db_user, 15, edit=True)


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
        deadlines_data = await deadline_service.get_user_deadlines(
            db_user.tg_user_id, days
        )

        # Форматируем сообщение
        text = deadline_service.format_deadlines_list(
            deadlines_data, days, user_tz_name=db_user.timezone
        )

        # Создаем клавиатуру с периодами и действиями
        builder = InlineKeyboardBuilder()

        periods = [(7, "7 дней"), (15, "15 дней"), (30, "30 дней")]

        for period_days, period_text in periods:
            if period_days == days:
                button_text = f"✅ {period_text}"
                callback_data = f"current_{period_days}"
            else:
                button_text = period_text
                callback_data = f"deadlines_{period_days}"

            builder.button(text=button_text, callback_data=callback_data)

        builder.row()

        if not deadlines_data:
            builder.button(text="📚 Подписки", callback_data="quick_sub")

        builder.button(text="🔙 Назад", callback_data="back_to_menu")
        builder.adjust(3, 2)

        if edit:
            await message.edit_text(
                text, reply_markup=builder.as_markup(), disable_web_page_preview=True
            )
        else:
            await message.answer(
                text, reply_markup=builder.as_markup(), disable_web_page_preview=True
            )

        logger.info(
            f"Пользователь {db_user.tg_user_id} запросил дедлайны на {days} дней"
        )

    except Exception as e:
        logger.error(f"Ошибка отправки списка дедлайнов: {e}")
        error_text = "Произошла ошибка при получении дедлайнов. Попробуйте позже."

        if edit:
            await message.edit_text(error_text)
        else:
            await message.answer(error_text)


@router.callback_query(F.data.startswith("current_"))
async def callback_current_period(callback: CallbackQuery):
    """Обработчик нажатия на текущий период"""
    await callback.answer("Уже выбран этот период", show_alert=False)


def register_deadline_handlers(dp):
    """Регистрация handlers для дедлайнов"""
    dp.include_router(router)
