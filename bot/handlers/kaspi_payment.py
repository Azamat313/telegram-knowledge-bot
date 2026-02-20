"""
Обработчики оплаты через Kaspi Pay.
Flow: выбор Kaspi → ссылка на оплату → фото чека → GPT Vision проверка (сумма + дата) → подписка.
"""

import io
from datetime import datetime

from aiogram import Bot, Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from loguru import logger

from config import KASPI_PAY_LINK, KASPI_PRICE_KZT, KASPI_PLAN_DAYS
from database.db import Database
from core.ai_engine import AIEngine
from core.messages import get_msg
from bot.states.kaspi import KaspiPaymentStates

router = Router()


def _get_cancel_keyboard(lang: str = "kk") -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой отмены."""
    cancel_text = "Бас тарту ❌" if lang == "kk" else "Отмена ❌"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=cancel_text, callback_data="kaspi_cancel")],
    ])


def _is_today(date_str: str) -> bool:
    """Проверяет, является ли дата (ДД.ММ.ГГГГ) сегодняшней."""
    today = datetime.now()
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(date_str.strip(), fmt)
            return parsed.date() == today.date()
        except ValueError:
            continue
    return False


@router.callback_query(F.data == "kaspi_pay")
async def on_kaspi_select(callback: CallbackQuery, db: Database, state: FSMContext, **kwargs):
    """Пользователь выбрал оплату через Kaspi."""
    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    lang = user.get("language", "kk") if user else "kk"

    # Проверяем, нет ли уже pending платежа
    existing = await db.get_pending_kaspi_payment(user_id)
    if existing:
        payment_id = existing["id"]
    else:
        payment_id = await db.create_kaspi_payment(
            user_telegram_id=user_id,
            amount=KASPI_PRICE_KZT,
            plan_days=KASPI_PLAN_DAYS,
        )

    await state.set_state(KaspiPaymentStates.waiting_for_receipt)
    await state.update_data(payment_id=payment_id)

    await callback.message.answer(
        get_msg("kaspi_instructions", lang,
                link=KASPI_PAY_LINK,
                amount=KASPI_PRICE_KZT),
        reply_markup=_get_cancel_keyboard(lang),
    )
    await callback.answer()
    logger.info(f"Kaspi payment started: user={user_id}, payment_id={payment_id}")


@router.message(KaspiPaymentStates.waiting_for_receipt, F.photo)
async def on_receipt_photo(message: Message, db: Database, ai_engine: AIEngine,
                           state: FSMContext, bot: Bot, **kwargs):
    """Пользователь отправил фото чека."""
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    lang = user.get("language", "kk") if user else "kk"

    # Получаем pending платёж
    payment = await db.get_pending_kaspi_payment(user_id)
    if not payment:
        await state.clear()
        return

    # Скачиваем фото
    file_id = message.photo[-1].file_id
    file = await bot.get_file(message.photo[-1].file_id)
    buffer = io.BytesIO()
    await bot.download_file(file.file_path, buffer)
    image_bytes = buffer.getvalue()

    # Анализируем через GPT Vision
    result = await ai_engine.analyze_receipt(image_bytes)

    if not result or result.get("amount") is None:
        await message.answer(
            get_msg("kaspi_error_parse", lang),
            reply_markup=_get_cancel_keyboard(lang),
        )
        logger.warning(f"Kaspi receipt parse failed: user={user_id}")
        return

    amount_found = result.get("amount")
    date_found = result.get("date", "")

    # Сохраняем результат анализа
    await db.update_kaspi_payment(
        payment_id=payment["id"],
        amount_found=float(amount_found) if amount_found else None,
        comment_found=date_found,  # храним дату в поле comment_found
        receipt_file_id=file_id,
    )

    # Проверяем сумму
    amount_ok = amount_found is not None and float(amount_found) >= payment["amount_expected"]
    # Проверяем дату (сегодняшняя)
    date_ok = bool(date_found) and _is_today(str(date_found))

    if not amount_ok:
        await message.answer(
            get_msg("kaspi_error_amount", lang, expected=int(payment["amount_expected"])),
            reply_markup=_get_cancel_keyboard(lang),
        )
        logger.info(f"Kaspi amount mismatch: user={user_id}, expected={payment['amount_expected']}, found={amount_found}")
        return

    if not date_ok:
        await message.answer(
            get_msg("kaspi_error_date", lang),
            reply_markup=_get_cancel_keyboard(lang),
        )
        logger.info(f"Kaspi date mismatch: user={user_id}, date_found={date_found}")
        return

    # Всё совпало — активируем подписку
    await db.grant_subscription(
        telegram_id=user_id,
        plan_name="kaspi",
        days=payment["plan_days"],
        amount=payment["amount_expected"],
        currency="KZT",
        payment_method="kaspi",
        payment_id=str(payment["id"]),
    )

    await db.update_kaspi_payment(
        payment_id=payment["id"],
        status="auto_approved",
    )

    await state.clear()

    await message.answer(get_msg("kaspi_success", lang, days=payment["plan_days"]))
    logger.info(f"Kaspi payment auto_approved: user={user_id}, amount={amount_found}, date={date_found}")


@router.message(KaspiPaymentStates.waiting_for_receipt)
async def on_receipt_not_photo(message: Message, db: Database, state: FSMContext, **kwargs):
    """Пользователь отправил не фото в состоянии ожидания чека."""
    user = await db.get_user(message.from_user.id)
    lang = user.get("language", "kk") if user else "kk"

    await message.answer(
        get_msg("kaspi_send_photo", lang),
        reply_markup=_get_cancel_keyboard(lang),
    )


@router.callback_query(F.data == "kaspi_cancel")
async def on_kaspi_cancel(callback: CallbackQuery, state: FSMContext, db: Database, **kwargs):
    """Отмена Kaspi-оплаты."""
    user = await db.get_user(callback.from_user.id)
    lang = user.get("language", "kk") if user else "kk"

    await state.clear()
    await callback.message.edit_text(get_msg("kaspi_cancelled", lang))
    await callback.answer()
