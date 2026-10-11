"""Conservative size guard for ordinary Telegram messages."""

# Bot API sendMessage allows 4096 visible characters after entity parsing.
# Leave room for formatting and future copy changes.
SAFE_MESSAGE_LENGTH = 3500


class MessageTooLongError(ValueError):
    """A notification must be split before attempting delivery."""
