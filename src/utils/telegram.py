"""
Утилиты для работы с Telegram API.
"""

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message
from loguru import logger


async def safe_edit_message(message: Message, text: str, **kwargs):
    """
    Безопасное редактирование сообщения с обработкой ошибок Telegram API.

    Обрабатывает следующие ошибки:
    - "message is not modified" - сообщение не изменилось (игнорируется)
    - "message not found" - сообщение удалено (игнорируется)
    - TelegramForbiddenError - бот заблокирован (игнорируется)

    Args:
        message: Объект сообщения для редактирования
        text: Текст сообщения
        **kwargs: Дополнительные параметры для edit_text

    Returns:
        bool: True если сообщение успешно отредактировано, False если произошла ошибка
    """
    try:
        await message.edit_text(text, **kwargs)
        return True
    except TelegramBadRequest as e:
        error_msg = str(e).lower()
        if "message is not modified" in error_msg or "message not found" in error_msg:
            # Сообщение не изменилось или удалено - это нормально
            return False
        # Другие ошибки пробрасываем дальше
        raise
    except TelegramForbiddenError:
        # Бот заблокирован пользователем
        return False
    except Exception:
        # Все остальные ошибки пробрасываем
        raise


async def _deactivate_user(user_id: int):
    """Внутренняя функция деактивации пользователя"""
    try:
        from src.core.database import db_manager
        from src.core.models import User

        async with db_manager.async_session() as session:
            user = await session.get(User, user_id)
            if user and user.is_active:
                user.is_active = False
                await session.commit()
                logger.info(f"(U) {user_id} - Деактивирован")
    except Exception as e:
        logger.error(f"(U) {user_id} - Ошибка деактивации: {e}")


async def safe_send_message(
    bot: Bot,
    chat_id: int,
    text: str,
    user_id: int | None = None,
    success_message: str | None = None,
    **kwargs
) -> bool:
    """
    Безопасная отправка сообщения с автоматической обработкой ошибок, логированием и деактивацией.

    Обрабатывает следующие ошибки:
    - TelegramForbiddenError - бот заблокирован пользователем (логирует + деактивирует пользователя)
    - TelegramBadRequest - различные ошибки API (логирует, не деактивирует)
    - Прочие исключения пробрасываются дальше

    Автоматически применяет режим сна и деактивирует пользователя при блокировке, если передан user_id.

    Args:
        bot: Объект бота для отправки сообщения
        chat_id: ID чата для отправки сообщения
        text: Текст сообщения
        user_id: ID пользователя для логирования, деактивации и проверки режима сна (опционально)
        success_message: Сообщение для логирования при успехе (опционально)
        **kwargs: Дополнительные параметры для send_message (parse_mode, reply_markup и т.д.)

    Returns:
        bool: True если отправка успешна, False если была ошибка
    """
    # Применяем режим сна, если передан user_id
    if user_id:
        from src.core.database import db_manager
        from src.utils.notification import apply_sleep_mode

        try:
            # Получаем пользователя и его настройки
            user = await db_manager.get_user_by_id(user_id)
            if user:
                settings = await db_manager.get_user_notification_settings(user_id)
                text, is_sleep = apply_sleep_mode(user, settings, text)
                if is_sleep:
                    kwargs["disable_notification"] = True
        except Exception as e:
            # Не критично, если не удалось проверить режим сна - просто отправляем как есть
            logger.debug(f"Не удалось проверить режим сна для пользователя {user_id}: {e}")

    try:
        await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        if success_message:
            logger.info(success_message)
        return True
    except TelegramForbiddenError:
        user_prefix = f"(U) {user_id} - " if user_id else ""
        logger.warning(f"{user_prefix}Заблокирован")
        if user_id:
            await _deactivate_user(user_id)
        return False
    except TelegramBadRequest as e:
        user_prefix = f"(U) {user_id} - " if user_id else ""
        logger.warning(f"{user_prefix}Ошибка отправки: {e}")
        return False
    except Exception:
        raise

