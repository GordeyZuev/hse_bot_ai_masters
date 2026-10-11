from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from aiogram import BaseMiddleware
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import Message

from src.bot.services.user_action_events import record_user_action_event
from src.utils import get_logger


logger = get_logger()


class MessageAuditMiddleware(BaseMiddleware):
    """Log every incoming message type without retaining private message content."""

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        if event.from_user:
            command = (
                event.text.split(maxsplit=1)[0].split("@", 1)[0]
                if event.text and event.text.startswith("/")
                else None
            )
            if command and (
                len(command) > 64 or not command[1:].replace("_", "").isalnum()
            ):
                command = None
            action = (
                f"команда {command}" if command else f"сообщение {event.content_type}"
            )
            logger.info(f"(U) {event.from_user.id} - Входящее {action}")
        chat = getattr(event, "chat", None)
        event_data = (
            {
                "user_id": event.from_user.id,
                "event_name": "message_received",
                "occurred_at": datetime.now(UTC),
                "surface": getattr(chat, "type", None),
                "chat_id": getattr(chat, "id", None),
                "message_id": getattr(event, "message_id", None),
                "details": (
                    {"command": command}
                    if command
                    else {"content_type": str(event.content_type)}
                ),
            }
            if event.from_user
            else None
        )
        try:
            result = await handler(event, data)
        except Exception:
            if event_data:
                await record_user_action_event(**event_data, outcome="failed")
            raise
        if event_data:
            await record_user_action_event(
                **event_data,
                outcome="unhandled" if result is UNHANDLED else "handled",
            )
        return result
