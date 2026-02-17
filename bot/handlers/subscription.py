"""
Обработчики подписки и оплаты.
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery
from loguru import logger

from config import SUBSCRIPTION_PLANS, MSG_SUBSCRIPTION_ACTIVE
from database.db import Database
from bot.keyboards.inline import get_confirm_subscription_keyboard

router = Router()


@router.callback_query(F.data.startswith("subscribe:"))
async def on_subscribe_select(callback: CallbackQuery, db: Database, **kwargs):
    """Выбор тарифа подписки."""
    plan_key = callback.data.split(":")[1]
    plan = SUBSCRIPTION_PLANS.get(plan_key)

    if not plan:
        await callback.answer("Неизвестный тариф", show_alert=True)
        return

    price = plan["price"]
    currency = plan["currency"]
    days = plan["days"]

    text = (
        f"Вы выбрали тариф:\n\n"
        f"Стоимость: {price} {currency}\n"
        f"Срок: {days} дней\n\n"
        f"Для оплаты свяжитесь с администратором или используйте кнопку ниже.\n"
        f"(Интеграция с платёжной системой — по согласованию)"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_confirm_subscription_keyboard(plan_key),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_sub:"))
async def on_confirm_subscription(callback: CallbackQuery, db: Database, **kwargs):
    """
    Подтверждение подписки.
    В продакшене здесь будет интеграция с Kaspi Pay / Telegram Payments.
    Сейчас — активация по нажатию (для тестирования / ручной оплаты).
    """
    plan_key = callback.data.split(":")[1]
    plan = SUBSCRIPTION_PLANS.get(plan_key)

    if not plan:
        await callback.answer("Неизвестный тариф", show_alert=True)
        return

    user_id = callback.from_user.id

    await db.grant_subscription(
        telegram_id=user_id,
        plan_name=plan_key,
        days=plan["days"],
        amount=plan["price"],
        currency=plan["currency"],
        payment_method="manual",
    )

    user = await db.get_user(user_id)
    expires = user.get("subscription_expires_at", "")[:10] if user else "—"

    await callback.message.edit_text(
        MSG_SUBSCRIPTION_ACTIVE.format(expires_at=expires)
    )
    await callback.answer("Подписка активирована!", show_alert=True)
    logger.info(f"Subscription activated: user={user_id}, plan={plan_key}")


@router.callback_query(F.data == "cancel_sub")
async def on_cancel_subscription(callback: CallbackQuery, **kwargs):
    """Отмена оформления подписки."""
    await callback.message.edit_text("Оформление подписки отменено.")
    await callback.answer()
