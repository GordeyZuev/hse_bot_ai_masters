from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from src.bot.services.chat_service import chat_service
from src.utils import get_logger


logger = get_logger()


class GroupChatMiddleware(BaseMiddleware):
    """Middleware для обработки ошибок в групповых чатах (например, закрытые топики)"""

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception as e:
            chat = event.chat if hasattr(event, "chat") else (event.message.chat if hasattr(event, "message") else None)
            if chat and chat.type in ["group", "supergroup"]:
                # Перехватываем ошибку закрытого топика (штатная ситуация)
                err_str = str(e).lower()
                if "topic_closed" in err_str:
                    logger.warning(f"[C] TOPIC_CLOSED в {chat.id}: {e}")
                    await self.handle_topic_closed_error(event, chat)
                    raise
                # Логируем другие ошибки групповых чат
                logger.error(f"Ошибка в групповом чате {chat.id}: {e}")
            # Пробрасываем ошибки дальше
            raise

    async def resolve_topic_title(self, message: Message, chat_id: int, topic_id: int | None) -> str | None:
        """Получить название топика из сообщения или через API"""
        try:
            # Пытаемся взять из reply_to_message.forum_topic_created
            rtc = getattr(message, "reply_to_message", None)
            ftc = getattr(rtc, "forum_topic_created", None) if rtc else None
            if ftc:
                title_from_message = getattr(ftc, "name", None) or getattr(ftc, "title", None)
                if title_from_message:
                    return title_from_message
        except Exception:
            pass

        try:
            if topic_id:
                return await chat_service.get_topic_title(message.bot, chat_id, topic_id)
        except Exception:
            pass

        return None

    async def handle_topic_closed_error(self, event: Message | CallbackQuery, chat):
        """Обработать ошибку закрытого топика - отправить уведомление в общий чат"""
        try:
            message = event if isinstance(event, Message) else event.message
            if not message:
                return

            chat_id = chat.id
            topic_id = getattr(message, "message_thread_id", None)

            # Получаем название топика
            topic_title = await self.resolve_topic_title(message, chat_id, topic_id)
            topic_label = topic_title or (f"ID {topic_id}" if topic_id else "топик")

            notice = (
                f"<b>⚠️ Топик «{topic_label}» закрыт.</b>\n\n"
                "Боту нужно право <b>«Управление темами»</b>\n"
                "Выдайте право или вызовите бота в открытом топике."
            )

            bot = message.bot
            await bot.send_message(chat_id=chat_id, text=notice, parse_mode="HTML")
            logger.debug(f"Отправлено уведомление о закрытом топике в чат {chat_id}, топик {topic_id}")
        except Exception as e:
            # Ошибка при обработке TOPIC_CLOSED - штатная ситуация, не логируем как ошибку
            logger.warning(f"Не удалось отправить уведомление о закрытом топике в чат {chat_id}: {e}")

