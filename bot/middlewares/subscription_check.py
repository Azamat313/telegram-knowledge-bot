"""
Middleware для проверки подписки и лимитов бесплатных ответов.
Пропускает пользователей в OnboardingStates.
"""

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from config import FREE_ANSWERS_LIMIT
from core.messages import get_msg
from database.db import Database
from bot.keyboards.inline import get_subscription_keyboard
from bot.states.onboarding import OnboardingStates
from bot.states.kaspi import KaspiPaymentStates


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

        # Пропускаем платёжные сообщения (successful_payment, invoice)
        if event.successful_payment:
            return await handler(event, data)

        # Пропускаем команды (они обрабатываются отдельно)
        if event.text and event.text.startswith("/"):
            return await handler(event, data)

        user_id = event.from_user.id

        # Пропускаем пользователей в онбординге или Kaspi-оплате
        state: FSMContext = data.get("state")
        if state:
            current_state = await state.get_state()
            if current_state and (
                current_state.startswith("OnboardingStates:")
                or current_state.startswith("KaspiPaymentStates:")
            ):
                return await handler(event, data)

        user = await self.db.get_or_create_user(
            telegram_id=user_id,
            username=event.from_user.username,
            first_name=event.from_user.first_name,
        )

        # Добавляем язык пользователя в data для хендлеров
        user_lang = user.get("language", "kk")
        data["user_lang"] = user_lang

        # Проверяем подписку
        is_subscribed = await self.db.check_subscription(user_id)
        if is_subscribed:
            data["user"] = user
            data["is_subscribed"] = True
            return await handler(event, data)

        # Проверяем лимит бесплатных ответов
        if user["answers_count"] >= FREE_ANSWERS_LIMIT:
            await event.answer(
                get_msg("limit_reached", user_lang, limit=FREE_ANSWERS_LIMIT),
                reply_markup=get_subscription_keyboard(lang=user_lang),
            )
            return None

        data["user"] = user
        data["is_subscribed"] = False
        return await handler(event, data)
