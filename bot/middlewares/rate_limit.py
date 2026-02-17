"""
Middleware для rate limiting — защита от спама.
Максимум RATE_LIMIT_PER_MINUTE запросов в минуту на пользователя.
"""

import time
from collections import defaultdict
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message

from config import RATE_LIMIT_PER_MINUTE, MSG_RATE_LIMIT


class RateLimitMiddleware(BaseMiddleware):
    def __init__(self, limit: int = RATE_LIMIT_PER_MINUTE):
        self.limit = limit
        # {user_id: [timestamp1, timestamp2, ...]}
        self._requests: Dict[int, list] = defaultdict(list)

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not event.from_user:
            return await handler(event, data)

        user_id = event.from_user.id
        now = time.time()

        # Очистка памяти при большом количестве пользователей
        if len(self._requests) > 5000:
            stale_users = [
                uid for uid, timestamps in self._requests.items()
                if not timestamps or now - timestamps[-1] > 120
            ]
            for uid in stale_users:
                del self._requests[uid]

        # Очищаем старые записи (старше 60 секунд)
        self._requests[user_id] = [
            ts for ts in self._requests[user_id] if now - ts < 60
        ]

        if len(self._requests[user_id]) >= self.limit:
            await event.answer(MSG_RATE_LIMIT)
            return None

        self._requests[user_id].append(now)
        return await handler(event, data)
