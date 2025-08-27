from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.bot.services.subscription_service import subscription_service
from src.utils import get_logger

logger = get_logger()
router = Router()

class SubscriptionStates(StatesGroup):
    choosing_year = State()
    choosing_subject = State()

@router.message(Command("sub"))
@router.message(Command("mysubs"))
@router.callback_query(F.data == "quick_sub")
@router.callback_query(F.data == "quick_mysubs")
async def cmd_subscriptions(event: Message | CallbackQuery, db_user, state: FSMContext):
    """Обработчик команд /sub и /mysubs - единый интерфейс подписок"""
    if isinstance(event, CallbackQuery):
        await event.answer()
        message = event.message
        edit_mode = True
    else:
        message = event
        edit_mode = False
    
    try:
        # Получаем текущие подписки пользователя
        subscriptions = await subscription_service.get_user_subscriptions(db_user.tg_user_id)
        
        # Группируем по курсам
        by_year = {}
        for sub in subscriptions:
            if sub.year not in by_year:
                by_year[sub.year] = []
            by_year[sub.year].append(sub)
        
        text = "📚 <b>Мои подписки</b>\n\n"
        
        if subscriptions:
            for year in sorted(by_year.keys()):
                text += f"<b>{year} курс ({len(by_year[year])}):</b>\n"
                for subject in by_year[year]:
                    text += f"• {subject.name}\n"
                text += "\n"
            
            text += f"<i>Всего подписок: {len(subscriptions)}</i>\n\n"
            text += "Выберите курс для управления подписками:"
        else:
            text += "У вас пока нет подписок на предметы.\n\n"
            text += "Выберите курс для подписки:"
        
        builder = InlineKeyboardBuilder()
        
        builder.button(text="1️⃣ Первый курс", callback_data="sub_year_1")
        builder.button(text="2️⃣ Второй курс", callback_data="sub_year_2")
        
        if subscriptions:
            builder.row()
            builder.button(text="🗑 Отписаться от всего", callback_data="confirm_unsuball")
        
        builder.row()
        builder.button(text="🔙 Назад", callback_data="back_to_menu")
        
        # Настраиваем layout: первые 2 кнопки в ряд, остальные по одной
        if subscriptions:
            builder.adjust(2, 1, 1)  # 2 кнопки курсов, 1 отписка, 1 назад
        else:
            builder.adjust(2, 1)     # 2 кнопки курсов, 1 назад
        
        await state.set_state(SubscriptionStates.choosing_year)
        
        if edit_mode:
            await message.edit_text(text, reply_markup=builder.as_markup())
        else:
            await message.answer(text, reply_markup=builder.as_markup())
        
    except Exception as e:
        logger.error(f"Ошибка в обработчике подписок: {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")

@router.callback_query(F.data.startswith("sub_year_"))
async def process_year_choice(callback: CallbackQuery, db_user, state: FSMContext):
    """Обработка выбора курса"""
    await callback.answer()
    
    try:
        year = int(callback.data.split("_")[-1])
        await show_subjects_for_year(callback.message, db_user, year, state)
        
    except Exception as e:
        logger.error(f"Ошибка выбора курса: {e}")
        await callback.answer("Произошла ошибка. Попробуйте позже.", show_alert=True)

async def show_subjects_for_year(message: Message, db_user, year: int, state: FSMContext):
    """Показать предметы для выбранного курса"""
    try:
        subjects = await subscription_service.get_subjects_by_year(year)
        
        if not subjects:
            await message.edit_text(f"Предметы {year} курса не найдены.")
            return
        
        # Получаем текущие подписки пользователя
        user_subscriptions = await subscription_service.get_user_subscriptions(db_user.tg_user_id)
        subscribed_ids = {sub.id for sub in user_subscriptions}
        
        # Подсчитываем статистику
        subscribed_count = len([s for s in subjects if s.id in subscribed_ids])
        total_count = len(subjects)
        
        text = f"📚 <b>Предметы {year} курса</b>\n\n"
        text += f"Подписок: {subscribed_count}/{total_count}\n\n"
        text += "Нажмите на предмет для подписки/отписки:"
        
        builder = InlineKeyboardBuilder()
        for subject in subjects:
            if subject.id in subscribed_ids:
                button_text = f"✅ {subject.name}"
                callback_data = f"toggle_sub_{subject.id}"
            else:
                button_text = f"📖 {subject.name}"
                callback_data = f"toggle_sub_{subject.id}"
            
            builder.button(text=button_text, callback_data=callback_data)
        
        builder.row()
        builder.button(text="🔙 Назад к выбору курса", callback_data="back_to_year_choice")
        builder.adjust(1)
        
        await state.update_data(year=year)
        await state.set_state(SubscriptionStates.choosing_subject)
        await message.edit_text(text, reply_markup=builder.as_markup())
        
    except Exception as e:
        logger.error(f"Ошибка показа предметов: {e}")
        await message.edit_text("Произошла ошибка при загрузке предметов.")

@router.callback_query(F.data.startswith("toggle_sub_"))
async def process_toggle_subscription(callback: CallbackQuery, db_user, state: FSMContext):
    """Обработка переключения подписки на предмет"""
    await callback.answer()
    
    try:
        subject_id = int(callback.data.split("_")[-1])
        
        # Проверяем текущий статус подписки
        user_subscriptions = await subscription_service.get_user_subscriptions(db_user.tg_user_id)
        subscribed_ids = {sub.id for sub in user_subscriptions}
        
        if subject_id in subscribed_ids:
            # Отписываемся
            success, message_text = await subscription_service.unsubscribe_user(db_user.tg_user_id, subject_id)
            action = "отписка"
        else:
            # Подписываемся
            success, message_text = await subscription_service.subscribe_user(db_user.tg_user_id, subject_id)
            action = "подписка"
        
        if success:
            await callback.answer(f"✅ {message_text}", show_alert=False)
            # Обновляем интерфейс
            data = await state.get_data()
            year = data.get('year', 1)
            await show_subjects_for_year(callback.message, db_user, year, state)
        else:
            await callback.answer(f"❌ {message_text}", show_alert=True)
        
    except Exception as e:
        logger.error(f"Ошибка переключения подписки: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


@router.message(Command("unsuball"))
@router.callback_query(F.data == "confirm_unsuball")
async def cmd_unsubscribe_all(event: Message | CallbackQuery, db_user):
    """Обработчик команды /unsuball - подтверждение отписки от всех предметов"""
    if isinstance(event, CallbackQuery):
        await event.answer()
        message = event.message
        edit_mode = True
    else:
        message = event
        edit_mode = False
    
    try:
        subscriptions = await subscription_service.get_user_subscriptions(db_user.tg_user_id)
        
        if not subscriptions:
            text = "У вас нет активных подписок."
            builder = InlineKeyboardBuilder()
            builder.button(text="🔙 Назад", callback_data="back_to_menu")
            
            if edit_mode:
                await message.edit_text(text, reply_markup=builder.as_markup())
            else:
                await message.answer(text, reply_markup=builder.as_markup())
            return
        
        text = f"🗑 <b>Отписка от всех предметов</b>\n\n"
        text += f"Вы уверены, что хотите отписаться от всех {len(subscriptions)} предметов?\n\n"
        text += "<i>Это действие нельзя отменить.</i>"
        
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Да, отписаться от всего", callback_data="execute_unsuball")
        builder.button(text="❌ Отмена", callback_data="quick_mysubs")
        builder.adjust(1)
        
        if edit_mode:
            await message.edit_text(text, reply_markup=builder.as_markup())
        else:
            await message.answer(text, reply_markup=builder.as_markup())
        
    except Exception as e:
        logger.error(f"Ошибка в обработчике /unsuball: {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")

@router.callback_query(F.data == "execute_unsuball")
async def execute_unsubscribe_all(callback: CallbackQuery, db_user):
    """Выполнение отписки от всех предметов"""
    await callback.answer()
    
    try:
        success, message_text = await subscription_service.unsubscribe_user_from_all(db_user.tg_user_id)
        
        text = f"🗑 <b>Отписка от всех предметов</b>\n\n{message_text}"
        
        builder = InlineKeyboardBuilder()
        builder.button(text="📚 Подписаться заново", callback_data="quick_sub")
        builder.button(text="🔙 Назад", callback_data="back_to_menu")
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
        
    except Exception as e:
        logger.error(f"Ошибка выполнения отписки от всего: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)

# Удаляем старые команды /unsub, так как теперь все в /sub

# Обработчики навигации
@router.callback_query(F.data == "back_to_year_choice")
async def back_to_year_choice(callback: CallbackQuery, db_user, state: FSMContext):
    """Возврат к выбору курса"""
    await callback.answer()
    await cmd_subscriptions(callback, db_user, state)

@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    """Возврат в главное меню"""
    await callback.answer()
    await state.clear()
    
    text = "🏠 <b>Главное меню</b>\n\nВыберите действие:"
    
    builder = InlineKeyboardBuilder()
    builder.button(text="📚 Подписки", callback_data="quick_sub")
    builder.button(text="📅 Дедлайны", callback_data="quick_deadlines")
    builder.button(text="⚙️ Настройки", callback_data="quick_settings")
    builder.button(text="ℹ️ Помощь", callback_data="quick_help")
    builder.adjust(2, 2)  # 2 кнопки в первом ряду, 2 во втором
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())

def register_subscription_handlers(dp):
    """Регистрация handlers для подписок"""
    dp.include_router(router)