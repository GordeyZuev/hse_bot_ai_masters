from aiogram import F, Router
from aiogram.filters import Command, and_f
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.bot.services.subscription_service import subscription_service
from src.core.database import db_manager
from src.core.models import Subject
from src.utils import get_logger


logger = get_logger()
router = Router()


class SubscriptionStates(StatesGroup):
    choosing_year = State()
    choosing_subject = State()


@router.message(and_f(Command("sub"), F.chat.type == "private"))
@router.message(and_f(Command("mysubs"), F.chat.type == "private"))
@router.callback_query(F.data == "quick_sub")
@router.callback_query(F.data == "quick_mysubs")
async def cmd_subscriptions(event: Message | CallbackQuery, db_user, state: FSMContext):
    """Редирект старых команд в единый раздел Дисциплины."""
    if isinstance(event, CallbackQuery):
        await event.answer()
        # Переиспользуем общий раздел дисциплин
        await cmd_subjects(event, db_user, state)
    else:
        # Преобразуем в callback-совместимый вызов
        class _FakeCallback:
            def __init__(self, message: Message):
                self.message = message
        await cmd_subjects(_FakeCallback(event), db_user, state)


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


async def show_subjects_for_year(
    message: Message, db_user, year: int, state: FSMContext
):
    """Показать предметы для выбранного курса"""
    try:
        subjects = await subscription_service.get_subjects_by_year(year)

        if not subjects:
            await message.edit_text(f"Предметы {year} курса не найдены.")
            return

        # Получаем текущие подписки пользователя
        user_subscriptions = await subscription_service.get_user_subscriptions(
            db_user.tg_user_id
        )
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
        builder.button(text="🔙 Сохранить и выйти", callback_data="back_to_year_choice")
        builder.adjust(1)

        await state.update_data(year=year)
        await state.set_state(SubscriptionStates.choosing_subject)
        await message.edit_text(text, reply_markup=builder.as_markup())

    except Exception as e:
        logger.error(f"Ошибка показа предметов: {e}")
        await message.edit_text("Произошла ошибка при загрузке предметов.")


@router.callback_query(F.data.startswith("toggle_sub_"))
async def process_toggle_subscription(
    callback: CallbackQuery, db_user, state: FSMContext
):
    """Обработка переключения подписки на предмет"""
    await callback.answer()

    try:
        subject_id = int(callback.data.split("_")[-1])

        # Проверяем текущий статус подписки
        user_subscriptions = await subscription_service.get_user_subscriptions(
            db_user.tg_user_id
        )
        subscribed_ids = {sub.id for sub in user_subscriptions}

        if subject_id in subscribed_ids:
            # Отписываемся
            success, message_text = await subscription_service.unsubscribe_user(
                db_user.tg_user_id, subject_id
            )
        else:
            # Подписываемся
            success, message_text = await subscription_service.subscribe_user(
                db_user.tg_user_id, subject_id
            )

        if success:
            await callback.answer(f"✅ {message_text}", show_alert=True)
            # Обновляем интерфейс
            data = await state.get_data()
            year = data.get("year", 1)
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
        subscriptions = await subscription_service.get_user_subscriptions(
            db_user.tg_user_id
        )

        if not subscriptions:
            text = "У вас нет активных подписок."
            builder = InlineKeyboardBuilder()
            builder.button(text="🔙 Назад", callback_data="back_to_menu")

            if edit_mode:
                await message.edit_text(text, reply_markup=builder.as_markup())
            else:
                await message.answer(text, reply_markup=builder.as_markup())
            return

        text = "🗑 <b>Отписка от всех предметов</b>\n\n"
        text += f"Вы уверены, что хотите отписаться от всех {len(subscriptions)} предметов?\n\n"
        text += "<i>Это действие нельзя отменить.</i>"

        builder = InlineKeyboardBuilder()
        builder.button(
            text="✅ Да, отписаться от всего", callback_data="execute_unsuball"
        )
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
        success, message_text = await subscription_service.unsubscribe_user_from_all(
            db_user.tg_user_id
        )

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
    builder.button(text="📖 Дисциплины", callback_data="quick_subjects")
    builder.button(text="📅 Дедлайны", callback_data="quick_deadlines")
    builder.button(text="⚙️ Настройки", callback_data="quick_settings")
    builder.button(text="❓ Помощь", callback_data="quick_help")

    from src.bot.handlers.admin import is_admin

    if is_admin(callback.from_user.id):
        builder.row()
        builder.button(text="👨‍💼 Админ-панель", callback_data="admin_panel")
        builder.adjust(2, 2, 1)
    else:
        builder.adjust(2, 2)

    await callback.message.edit_text(text, reply_markup=builder.as_markup())


def register_subscription_handlers(dp):
    """Регистрация handlers для подписок"""
    dp.include_router(router)



@router.message(and_f(Command("subjects"), F.chat.type == "private"))
@router.callback_query(F.data == "quick_subjects")
async def cmd_subjects(event: Message | CallbackQuery, db_user, state: FSMContext):
    """Раздел дисциплин: выбор курса и просмотр активных/подписанных дисциплин."""
    if isinstance(event, CallbackQuery):
        await event.answer()
        message = event.message
        edit_mode = True
    else:
        message = event
        edit_mode = False

    try:
        subscriptions = await subscription_service.get_user_subscriptions(db_user.tg_user_id)
        by_year: dict[int, list] = {}
        for s in subscriptions:
            by_year.setdefault(s.year, []).append(s)

        text_lines = ["📖  <b>Ваши дисциплины</b>", ""]
        if subscriptions:
            subjects_sorted_all = sorted(subscriptions, key=lambda x: (x.year or 0, x.name))
            for subj in subjects_sorted_all:
                text_lines.append(f"🔹 <b>{subj.name}</b>")
                if getattr(subj, "wiki_url", None):
                    text_lines.append(f'• <a href="{subj.wiki_url}">Wiki</a>')
                if getattr(subj, "vk_playlist_url", None):
                    text_lines.append(f'• <a href="{subj.vk_playlist_url}">VK Video</a>')
                if getattr(subj, "yt_playlist_url", None):
                    text_lines.append(f'• <a href="{subj.yt_playlist_url}">YouTube</a>')
                text_lines.append("")
            text_lines.append("Если хотите изменить подписки, перейдите в разделы ниже.")
        else:
            text_lines.append("У вас пока нет подписок на предметы.")
            text_lines.append("")
            text_lines.append("")
            text_lines.append("Выберите курс ниже, чтобы подписаться:")

        text = "\n".join(text_lines)

        builder = InlineKeyboardBuilder()
        builder.button(text="1️⃣ Первый курс", callback_data="subjects_year_1")
        builder.button(text="2️⃣ Второй курс", callback_data="subjects_year_2")
        builder.row()
        builder.button(text="🔙 Назад", callback_data="back_to_menu")
        builder.adjust(2, 1)
    except Exception as e:
        logger.error(f"Ошибка подготовки раздела дисциплин: {e}")
        text = "Произошла ошибка при загрузке дисциплин."
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 Назад", callback_data="back_to_menu")
        builder.adjust(1)

    if edit_mode:
        await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML", disable_web_page_preview=True)
    else:
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML", disable_web_page_preview=True)


@router.callback_query(F.data.startswith("subjects_year_"))
async def subjects_year_to_subscribe(callback: CallbackQuery, db_user, state: FSMContext):
    """При выборе курса в разделе Дисциплины переходим к управлению подписками (как раньше)."""
    await callback.answer()

    try:
        year = int(callback.data.split("_")[-1])
        await show_subjects_for_year(callback.message, db_user, year, state)
    except Exception as e:
        logger.error(f"Ошибка перехода к управлению подписками: {e}")
        await callback.message.edit_text("Произошла ошибка при загрузке дисциплин.")


@router.callback_query(F.data.startswith("subject_info_"))
async def show_subject_info(callback: CallbackQuery, db_user):
    """Карточка дисциплины: модули + ссылки (wiki/vk/youtube)."""
    await callback.answer()

    try:
        subject_id = int(callback.data.split("_")[-1])
        async with db_manager.async_session() as session:
            from sqlalchemy import select
            stmt = select(Subject).where(Subject.id == subject_id)
            result = await session.execute(stmt)
            subject = result.scalar_one_or_none()

        if not subject:
            await callback.message.edit_text("Дисциплина не найдена.")
            return

        modules_text = None
        if subject.start_module and subject.end_module:
            if subject.start_module == subject.end_module:
                modules_text = f"{subject.start_module}"
            else:
                modules_text = f"{subject.start_module}-{subject.end_module}"

        text = (
            f"📚 <b>{subject.name}</b> (курс {subject.year})\n"
            + (f"Модули: {modules_text}\n\n" if modules_text else "\n")
        )

        if subject.wiki_url:
            text += f'🔗 <a href="{subject.wiki_url}">Wiki</a>\n'
        if subject.vk_playlist_url:
            text += f'▶️ <a href="{subject.vk_playlist_url}">VK</a>\n'
        if subject.yt_playlist_url:
            text += f'▶️ <a href="{subject.yt_playlist_url}">YouTube</a>\n'

        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 Назад", callback_data="quick_subjects")

        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Ошибка показа карточки дисциплины: {e}")
        await callback.message.edit_text("Произошла ошибка при показе дисциплины.")
