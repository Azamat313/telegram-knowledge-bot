"""
Middleware авторизации устазов.
Проверяет, что пользователь зарегистрирован как активный устаз.
"""

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

from config import MSG_USTAZ_NOT_REGISTERED
from database.db import Database


class UstazAuthMiddleware(BaseMiddleware):
    def __init__(self, db: Database):
        self.db = db

    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        user = event.from_user
        if not user:
            return await handler(event, data)

        # Пропускаем /start — устаз может не быть зарегистрирован
        if isinstance(event, Message) and event.text and event.text.startswith("/start"):
            return await handler(event, data)

        ustaz = await self.db.get_ustaz(user.id)
        if not ustaz or not ustaz.get("is_active"):
            if isinstance(event, Message):
                await event.answer(MSG_USTAZ_NOT_REGISTERED)
            elif isinstance(event, CallbackQuery):
                await event.answer(MSG_USTAZ_NOT_REGISTERED, show_alert=True)
            return None

        data["ustaz"] = ustaz
        return await handler(event, data)
