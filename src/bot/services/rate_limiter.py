import asyncio


class TelegramRateLimiter:
    """Small process-wide limiter for the free Bot API broadcast limit."""

    def __init__(self, messages_per_second: int = 25):
        self._interval = 1 / messages_per_second
        self._lock = asyncio.Lock()
        self._next_send = 0.0

    async def acquire(self) -> None:
        loop = asyncio.get_running_loop()
        async with self._lock:
            now = loop.time()
            delay = self._next_send - now
            if delay > 0:
                await asyncio.sleep(delay)
                now = loop.time()
            self._next_send = max(now, self._next_send) + self._interval


telegram_rate_limiter = TelegramRateLimiter()
