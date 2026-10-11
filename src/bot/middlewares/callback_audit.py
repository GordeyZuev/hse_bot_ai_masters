import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from aiogram import BaseMiddleware
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import CallbackQuery

from src.bot.services.user_action_events import record_user_action_event
from src.utils import get_logger


logger = get_logger()


def button_type(callback_data: str) -> str:
    """Group callback IDs into stable names for analytics."""
    return re.sub(r"(?<![A-Za-z])\d+", "{id}", callback_data)[:128]


class CallbackAuditMiddleware(BaseMiddleware):
    """Record every callback, including unmatched and failed button presses."""

    async def __call__(
        self,
        handler: Callable[[CallbackQuery, dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        callback_data = event.data or event.game_short_name or ""
        message = getattr(event, "message", None)
        chat = getattr(message, "chat", None)
        chat_id = getattr(chat, "id", None)
        message_id = getattr(message, "message_id", None)
        surface = getattr(chat, "type", None) or "inline"
        logger.info(
            f"(U) {event.from_user.id} - Кнопка: {callback_data!r} "
            f"chat={chat_id} message={message_id}"
        )
        event_data = {
            "user_id": event.from_user.id,
            "event_name": "button_clicked",
            "occurred_at": datetime.now(UTC),
            "surface": surface,
            "chat_id": chat_id,
            "message_id": message_id,
            "details": {
                "callback_data": callback_data[:128],
                "button_type": button_type(callback_data),
            },
        }
        try:
            result = await handler(event, data)
        except Exception:
            await record_user_action_event(**event_data, outcome="failed")
            raise
        await record_user_action_event(
            **event_data,
            outcome="unhandled" if result is UNHANDLED else "handled",
        )
        return result
