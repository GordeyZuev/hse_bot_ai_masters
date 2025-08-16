"""
Хендлеры для управления подписками на дисциплины.
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.db import UserCRUD, SubjectCRUD, SubscriptionCRUD, get_db_session
from src.utils import bot_logger


router = Router()


class SubscriptionStates(StatesGroup):
    """Состояния для управления подписками."""
    selecting_subjects = State()
    confirming_subscription = State()
    confirming_unsubscription = State()


@router.message(Command("subscribe"))
async def subscribe_command_handler(message: Message, state: FSMContext):
    """Обработчик команды /subscribe."""
    await show_subscribe_menu(message, state=state)


@router.message(Command("my_subscriptions"))
async def my_subscriptions_command_handler(message: Message):
    """Обработчик команды /my_subscriptions."""
    await show_my_subscriptions(message)


@router.callback_query(F.data == "subscribe")
async def subscribe_callback_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик callback для подписки."""
    await show_subscribe_menu(callback.message, callback, state)


@router.callback_query(F.data == "my_subscriptions")
async def my_subscriptions_callback_handler(callback: CallbackQuery):
    """Обработчик callback для просмотра подписок."""
    await show_my_subscriptions(callback.message, callback)


@router.callback_query(F.data.startswith("subscribe_subject:"))
async def subscribe_subject_handler(callback: CallbackQuery):
    """Обработчик подписки на конкретную дисциплину."""
    user = callback.from_user
    subject_id = int(callback.data.split(":")[1])
    
    try:
        async with get_db_session() as session:
            # Получаем пользователя
            db_user = await UserCRUD.get_by_telegram_id(session, user.id)
            if not db_user:
                await callback.answer("❌ Пользователь не найден")
                return
            
            # Получаем дисциплину
            subject = await SubjectCRUD.get_by_id(session, subject_id)
            if not subject:
                await callback.answer("❌ Дисциплина не найдена")
                return
            
            # Подписываем пользователя
            subscription = await SubscriptionCRUD.subscribe(session, db_user.id, subject_id)
            
            await callback.answer(f"✅ Вы подписались на {subject.name}")
            
            bot_logger.user_action(
                user_id=user.id,
                action="subscribed",
                subject_name=subject.name,
                subject_id=subject_id
            )
            
            # Обновляем меню подписок
            await show_subscribe_menu(callback.message, callback)
            
    except Exception as e:
        bot_logger.error(f"Error subscribing to subject: {e}", user_id=user.id)
        await callback.answer("❌ Ошибка при подписке")


@router.callback_query(F.data.startswith("unsubscribe_subject:"))
async def unsubscribe_subject_handler(callback: CallbackQuery):
    """Обработчик отписки от конкретной дисциплины."""
    user = callback.from_user
    subject_id = int(callback.data.split(":")[1])
    
    try:
        async with get_db_session() as session:
            # Получаем пользователя
            db_user = await UserCRUD.get_by_telegram_id(session, user.id)
            if not db_user:
                await callback.answer("❌ Пользователь не найден")
                return
            
            # Получаем дисциплину
            subject = await SubjectCRUD.get_by_id(session, subject_id)
            if not subject:
                await callback.answer("❌ Дисциплина не найдена")
                return
            
            # Отписываем пользователя
            success = await SubscriptionCRUD.unsubscribe(session, db_user.id, subject_id)
            
            if success:
                await callback.answer(f"❌ Вы отписались от {subject.name}")
                
                bot_logger.user_action(
                    user_id=user.id,
                    action="unsubscribed",
                    subject_name=subject.name,
                    subject_id=subject_id
                )
            else:
                await callback.answer("❌ Вы не были подписаны на эту дисциплину")
            
            # Обновляем меню подписок
            await show_my_subscriptions(callback.message, callback)
            
    except Exception as e:
        bot_logger.error(f"Error unsubscribing from subject: {e}", user_id=user.id)
        await callback.answer("❌ Ошибка при отписке")


async def show_subscribe_menu(message: Message, callback: CallbackQuery = None, state: FSMContext = None):
    """Показывает меню подписки на дисциплины."""
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
            
            # Получаем все активные дисциплины
            all_subjects = await SubjectCRUD.get_all_active(session)
            
            if not all_subjects:
                text = (
                    "📚 <b>Подписка на дисциплины</b>\n\n"
                    "🔍 Пока нет доступных дисциплин для подписки.\n"
                    "Дисциплины появятся после синхронизации с Google Sheets."
                )
                keyboard = InlineKeyboardBuilder()
                keyboard.button(text="🏠 Главное меню", callback_data="main_menu")
                
                if callback:
                    await callback.message.edit_text(text, reply_markup=keyboard.as_markup())
                    await callback.answer()
                else:
                    await message.answer(text, reply_markup=keyboard.as_markup())
                return
            
            # Получаем текущие подписки пользователя
            user_subscriptions = await SubscriptionCRUD.get_user_subscriptions(session, db_user.id)
            subscribed_subject_ids = {sub.subject_id for sub in user_subscriptions}
            
            # Формируем текст и клавиатуру
            text = (
                "📚 <b>Подписка на дисциплины</b>\n\n"
                "Выберите дисциплины, на которые хотите подписаться.\n"
                "Вы будете получать уведомления о дедлайнах по выбранным предметам.\n\n"
                f"📊 Доступно дисциплин: {len(all_subjects)}\n"
                f"✅ Ваших подписок: {len(subscribed_subject_ids)}"
            )
            
            keyboard = InlineKeyboardBuilder()
            
            # Добавляем кнопки для каждой дисциплины
            for subject in all_subjects:
                if subject.id in subscribed_subject_ids:
                    # Уже подписан
                    button_text = f"✅ {subject.name}"
                    callback_data = f"already_subscribed:{subject.id}"
                else:
                    # Не подписан
                    button_text = f"➕ {subject.name}"
                    callback_data = f"subscribe_subject:{subject.id}"
                
                keyboard.button(text=button_text, callback_data=callback_data)
            
            # Добавляем кнопки навигации
            keyboard.button(text="📋 Мои подписки", callback_data="my_subscriptions")
            keyboard.button(text="🏠 Главное меню", callback_data="main_menu")
            
            # Настраиваем расположение кнопок (по 1 в ряду для дисциплин, 2 для навигации)
            keyboard.adjust(1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2)
            
            if callback:
                await callback.message.edit_text(text, reply_markup=keyboard.as_markup())
                await callback.answer()
            else:
                await message.answer(text, reply_markup=keyboard.as_markup())
                
            bot_logger.user_action(
                user_id=user.id,
                action="subscribe_menu_viewed",
                available_subjects=len(all_subjects),
                user_subscriptions=len(subscribed_subject_ids)
            )
        
    except Exception as e:
        bot_logger.error(f"Error in subscribe menu: {e}", user_id=user.id)
        error_text = "❌ Ошибка при загрузке дисциплин"
        if callback:
            await callback.message.edit_text(error_text)
            await callback.answer()
        else:
            await message.answer(error_text)


@router.callback_query(F.data.startswith("already_subscribed:"))
async def already_subscribed_handler(callback: CallbackQuery):
    """Обработчик нажатия на уже подписанную дисциплину."""
    subject_id = int(callback.data.split(":")[1])
    
    try:
        async with get_db_session() as session:
            subject = await SubjectCRUD.get_by_id(session, subject_id)
            if subject:
                await callback.answer(f"✅ Вы уже подписаны на {subject.name}")
            else:
                await callback.answer("❌ Дисциплина не найдена")
    except Exception as e:
        await callback.answer("❌ Ошибка")


async def show_my_subscriptions(message: Message, callback: CallbackQuery = None):
    """Показывает текущие подписки пользователя."""
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
            
            # Получаем подписки пользователя
            subscriptions = await SubscriptionCRUD.get_user_subscriptions(session, db_user.id)
            
            if not subscriptions:
                text = (
                    "📋 <b>Мои подписки</b>\n\n"
                    "📭 У вас пока нет активных подписок.\n"
                    "Подпишитесь на дисциплины, чтобы получать уведомления о дедлайнах."
                )
                keyboard = InlineKeyboardBuilder()
                keyboard.button(text="➕ Подписаться", callback_data="subscribe")
                keyboard.button(text="🏠 Главное меню", callback_data="main_menu")
                keyboard.adjust(1)
                
                if callback:
                    await callback.message.edit_text(text, reply_markup=keyboard.as_markup())
                    await callback.answer()
                else:
                    await message.answer(text, reply_markup=keyboard.as_markup())
                return
            
            # Формируем список подписок
            subscription_list = []
            for i, subscription in enumerate(subscriptions, 1):
                subscription_list.append(f"{i}. {subscription.subject.name}")
            
            text = (
                "📋 <b>Мои подписки</b>\n\n"
                f"✅ Активных подписок: {len(subscriptions)}\n\n"
                + "\n".join(subscription_list) +
                "\n\n💡 Нажмите на дисциплину, чтобы отписаться от неё."
            )
            
            keyboard = InlineKeyboardBuilder()
            
            # Добавляем кнопки для отписки от каждой дисциплины
            for subscription in subscriptions:
                keyboard.button(
                    text=f"❌ {subscription.subject.name}",
                    callback_data=f"unsubscribe_subject:{subscription.subject.id}"
                )
            
            # Добавляем кнопки навигации
            keyboard.button(text="➕ Подписаться", callback_data="subscribe")
            keyboard.button(text="🏠 Главное меню", callback_data="main_menu")
            
            # Настраиваем расположение кнопок
            keyboard.adjust(1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2)
            
            if callback:
                await callback.message.edit_text(text, reply_markup=keyboard.as_markup())
                await callback.answer()
            else:
                await message.answer(text, reply_markup=keyboard.as_markup())
                
            bot_logger.user_action(
                user_id=user.id,
                action="my_subscriptions_viewed",
                subscriptions_count=len(subscriptions)
            )
        
    except Exception as e:
        bot_logger.error(f"Error in my subscriptions: {e}", user_id=user.id)
        error_text = "❌ Ошибка при загрузке подписок"
        if callback:
            await callback.message.edit_text(error_text)
            await callback.answer()
        else:
            await message.answer(error_text)


def register_subscription_handlers(dp):
    """Регистрирует хендлеры для подписок."""
    dp.include_router(router)