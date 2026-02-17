"""
Middleware для проверки подписки и лимитов бесплатных ответов.
"""

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message

from config import FREE_ANSWERS_LIMIT, MSG_LIMIT_REACHED
from database.db import Database
from bot.keyboards.inline import get_subscription_keyboard


class SubscriptionCheckMiddleware(BaseMiddleware):
    def __init__(self, db: Database):
        self.db = db

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not event.from_user:
            return await handler(event, data)

        # Пропускаем команды (они обрабатываются отдельно)
        if event.text and event.text.startswith("/"):
            return await handler(event, data)

        user_id = event.from_user.id
        user = await self.db.get_or_create_user(
            telegram_id=user_id,
            username=event.from_user.username,
            first_name=event.from_user.first_name,
        )

        # Проверяем подписку
        is_subscribed = await self.db.check_subscription(user_id)
        if is_subscribed:
            data["user"] = user
            data["is_subscribed"] = True
            return await handler(event, data)

        # Проверяем лимит бесплатных ответов
        if user["answers_count"] >= FREE_ANSWERS_LIMIT:
            await event.answer(
                MSG_LIMIT_REACHED.format(limit=FREE_ANSWERS_LIMIT),
                reply_markup=get_subscription_keyboard(),
            )
            return None

        data["user"] = user
        data["is_subscribed"] = False
        return await handler(event, data)
