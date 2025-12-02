from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, Message

from src.utils.logger import get_logger


logger = get_logger()


class TelegramErrorHandler:
    """Класс для обработки ошибок Telegram API

    Перенесено из src/utils/telegram.py
    Используется в middleware и утилитах для единообразной обработки ошибок.
    """

    @staticmethod
    async def deactivate_user(user_id: int):
        """Деактивировать пользователя в БД"""
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

    @staticmethod
    def is_ignorable_error(error: Exception) -> bool:
        """Проверить, является ли ошибка некритичной (можно игнорировать)"""
        if isinstance(error, TelegramBadRequest):
            error_msg = str(error).lower()
            if "message is not modified" in error_msg or "message not found" in error_msg:
                return True
        return False

    @staticmethod
    async def handle_telegram_error(error: Exception, user_id: int | None = None, chat_id: int | None = None) -> bool:
        """Обработать ошибку Telegram API

        Args:
            error: Исключение от Telegram API
            user_id: ID пользователя (для личных чатов)
            chat_id: ID чата (для групповых чатов)

        Returns:
            bool: True если ошибка обработана (не нужно пробрасывать), False если нужно пробросить
        """
        if isinstance(error, TelegramForbiddenError):
            if user_id:
                logger.warning(f"(U) {user_id} - Заблокирован")
                await TelegramErrorHandler.deactivate_user(user_id)
            elif chat_id:
                logger.warning(f"(C) {chat_id} - Заблокирован в чате")
            else:
                logger.warning("Заблокирован (неизвестный получатель)")
            return True  # Ошибка обработана, не пробрасываем

        if TelegramErrorHandler.is_ignorable_error(error):
            logger.debug(f"Игнорируем ошибку: {error}")
            return True  # Ошибка обработана, не пробрасываем

        return False  # Нужно пробросить ошибку дальше


class PrivateChatMiddleware(BaseMiddleware):
    """Middleware для обработки ошибок в личных чатах

    Обрабатывает следующие ошибки:
    - "message is not modified" - сообщение не изменилось (игнорируется)
    - "message not found" - сообщение удалено (игнорируется)
    - TelegramForbiddenError - бот заблокирован (деактивирует пользователя)
    """

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        # Обрабатываем ошибки для личных чатов
        try:
            return await handler(event, data)
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            # Проверяем, что это личный чат
            chat = event.chat if hasattr(event, "chat") else (event.message.chat if hasattr(event, "message") else None)
            if chat and chat.type == "private":
                user = event.from_user
                user_id = user.id if user else None

                # Обрабатываем ошибку через общий обработчик
                if await TelegramErrorHandler.handle_telegram_error(e, user_id):
                    return  # Ошибка обработана, не пробрасываем
            raise  # Пробрасываем другие ошибки


# Экспортируем функции для использования в коде (обратная совместимость)
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
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        user_id = message.from_user.id if message.from_user else None
        # Используем общий обработчик ошибок
        if await TelegramErrorHandler.handle_telegram_error(e, user_id):
            return False  # Ошибка обработана
        raise  # Другие ошибки пробрасываем
    except Exception:
        # Все остальные ошибки пробрасываем
        raise


async def safe_send_message(
    bot: Bot,
    chat_id: int,
    text: str,
    user_id: int | None = None,
    success_message: str | None = None,
    is_group_chat: bool = False,
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
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        # Используем общий обработчик ошибок
        # Передаем chat_id для групповых чатов, user_id для личных
        error_chat_id = chat_id if is_group_chat and not user_id else None
        if await TelegramErrorHandler.handle_telegram_error(e, user_id=user_id, chat_id=error_chat_id):
            # Ошибка обработана (заблокирован или некритичная ошибка)
            if isinstance(e, TelegramBadRequest):
                if user_id:
                    logger.warning(f"(U) {user_id} - Ошибка отправки: {e}")
                elif is_group_chat:
                    logger.warning(f"(C) {chat_id} - Ошибка отправки: {e}")
                else:
                    logger.warning(f"Ошибка отправки: {e}")
            return False
        raise  # Другие ошибки пробрасываем
    except Exception:
        raise

