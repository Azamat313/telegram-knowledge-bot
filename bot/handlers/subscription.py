"""
Обработчики подписки и оплаты через Telegram Stars.
Flow: выбор тарифа → инвойс → pre_checkout → successful_payment → активация.
"""

import json

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, LabeledPrice, PreCheckoutQuery
from loguru import logger

from config import (
    SUBSCRIPTION_PLANS,
    MSG_PAYMENT_SUCCESS,
    MSG_PAYMENT_TITLE,
    MSG_PAYMENT_DESCRIPTION,
)
from database.db import Database

router = Router()


@router.callback_query(F.data.startswith("subscribe:"))
async def on_subscribe_select(callback: CallbackQuery, **kwargs):
    """Выбор тарифа — отправляем Telegram Stars инвойс."""
    plan_key = callback.data.split(":")[1]
    plan = SUBSCRIPTION_PLANS.get(plan_key)
    user_id = callback.from_user.id

    logger.info(f"Subscribe button clicked: user={user_id}, plan={plan_key}")

    if not plan:
        logger.warning(f"Unknown plan: {plan_key}")
        await callback.answer("Белгісіз тариф", show_alert=True)
        return

    try:
        await callback.message.answer_invoice(
            title=MSG_PAYMENT_TITLE,
            description=f"{plan['label']}\n{MSG_PAYMENT_DESCRIPTION}",
            payload=json.dumps({"plan": plan_key}),
            currency="XTR",
            prices=[LabeledPrice(label=plan["label"], amount=plan["price"])],
            provider_token="",
        )
        logger.info(f"Invoice sent: user={user_id}, plan={plan_key}, price={plan['price']} XTR")
    except Exception as e:
        logger.error(f"Failed to send invoice: user={user_id}, error={e}")
        await callback.answer(f"Қате: {e}", show_alert=True)
        return

    await callback.answer()


@router.pre_checkout_query()
async def on_pre_checkout(pre_checkout_query: PreCheckoutQuery, **kwargs):
    """Подтверждение pre-checkout (в течение 10 секунд)."""
    user_id = pre_checkout_query.from_user.id
    logger.info(f"Pre-checkout received: user={user_id}, payload={pre_checkout_query.invoice_payload}")

    try:
        payload = json.loads(pre_checkout_query.invoice_payload)
        plan_key = payload.get("plan")
        if plan_key not in SUBSCRIPTION_PLANS:
            logger.warning(f"Pre-checkout rejected (unknown plan): user={user_id}, plan={plan_key}")
            await pre_checkout_query.answer(ok=False, error_message="Белгісіз тариф")
            return
    except Exception as e:
        logger.error(f"Pre-checkout error: user={user_id}, error={e}")
        await pre_checkout_query.answer(ok=False, error_message="Төлем қатесі")
        return

    await pre_checkout_query.answer(ok=True)
    logger.info(f"Pre-checkout approved: user={user_id}, plan={plan_key}")


@router.message(F.successful_payment)
async def on_successful_payment(message: Message, db: Database, **kwargs):
    """Успешная оплата Stars — активация подписки."""
    payment = message.successful_payment
    user_id = message.from_user.id
    logger.info(f"Successful payment received: user={user_id}, charge_id={payment.telegram_payment_charge_id}")

    try:
        payload = json.loads(payment.invoice_payload)
        plan_key = payload.get("plan")
    except Exception:
        plan_key = "monthly"

    plan = SUBSCRIPTION_PLANS.get(plan_key, SUBSCRIPTION_PLANS["monthly"])

    charge_id = payment.telegram_payment_charge_id

    await db.grant_subscription(
        telegram_id=user_id,
        plan_name=plan_key,
        days=plan["days"],
        amount=plan["price"],
        currency="XTR",
        payment_method="telegram_stars",
        payment_id=charge_id,
    )

    user = await db.get_user(user_id)
    expires = user.get("subscription_expires_at", "")[:10] if user else "—"

    await message.answer(
        MSG_PAYMENT_SUCCESS.format(
            plan_label=plan["label"],
            expires_at=expires,
        )
    )

    logger.info(
        f"Stars payment: user={user_id}, plan={plan_key}, "
        f"amount={plan['price']} XTR, charge_id={charge_id}"
    )
