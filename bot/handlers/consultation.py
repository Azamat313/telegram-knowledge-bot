"""
Обработчики консультаций с устазом (пользовательская сторона).
FSM: кнопка → подтверждение → ввод вопроса → сохранение в очередь.
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from loguru import logger

from config import (
    USTAZ_MONTHLY_LIMIT,
    MSG_ASK_USTAZ_CONFIRM,
    MSG_ASK_USTAZ_LIMIT,
    MSG_ASK_USTAZ_SENT,
    MSG_ASK_USTAZ_SUBSCRIBERS_ONLY,
    MSG_ASK_USTAZ_WRITE_QUESTION,
    MSG_ASK_USTAZ_CANCEL,
    MSG_USTAZ_NEW_QUESTION,
)
from database.db import Database
from bot.keyboards.inline import get_ustaz_confirm_keyboard

router = Router()


class ConsultationStates(StatesGroup):
    waiting_for_question = State()


@router.callback_query(F.data.startswith("ask_ustaz:"))
async def on_ask_ustaz_button(callback: CallbackQuery, db: Database, state: FSMContext, **kwargs):
    """Пользователь нажал 'Устазға сұрақ қою'."""
    user_id = callback.from_user.id

    # Проверяем подписку
    is_subscribed = await db.check_subscription(user_id)
    if not is_subscribed:
        await callback.answer(MSG_ASK_USTAZ_SUBSCRIBERS_ONLY, show_alert=True)
        return

    # Проверяем лимит
    can_ask, remaining = await db.check_ustaz_limit(user_id)
    if not can_ask:
        await callback.answer(
            MSG_ASK_USTAZ_LIMIT.format(limit=USTAZ_MONTHLY_LIMIT),
            show_alert=True,
        )
        return

    # Извлекаем query_log_id из callback
    query_log_id = int(callback.data.split(":")[1])

    # Показываем подтверждение
    text = MSG_ASK_USTAZ_CONFIRM.format(
        limit=USTAZ_MONTHLY_LIMIT,
        remaining=remaining,
    )
    await callback.message.answer(
        text,
        reply_markup=get_ustaz_confirm_keyboard(query_log_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_ustaz:"))
async def on_confirm_ustaz(callback: CallbackQuery, db: Database, state: FSMContext, **kwargs):
    """Пользователь подтвердил — ожидаем текст вопроса."""
    user_id = callback.from_user.id
    query_log_id = int(callback.data.split(":")[1])

    # Проверяем лимит ещё раз
    can_ask, remaining = await db.check_ustaz_limit(user_id)
    if not can_ask:
        await callback.answer(
            MSG_ASK_USTAZ_LIMIT.format(limit=USTAZ_MONTHLY_LIMIT),
            show_alert=True,
        )
        return

    # Сохраняем query_log_id в FSM
    await state.set_state(ConsultationStates.waiting_for_question)
    await state.update_data(query_log_id=query_log_id)

    await callback.message.edit_text(MSG_ASK_USTAZ_WRITE_QUESTION)
    await callback.answer()


@router.callback_query(F.data == "cancel_ustaz")
async def on_cancel_ustaz(callback: CallbackQuery, state: FSMContext, **kwargs):
    """Отмена отправки вопроса устазу."""
    await state.clear()
    await callback.message.edit_text(MSG_ASK_USTAZ_CANCEL)
    await callback.answer()


@router.message(ConsultationStates.waiting_for_question, F.text)
async def on_question_text(message: Message, db: Database, state: FSMContext, **kwargs):
    """Пользователь ввёл текст вопроса для устаза."""
    user_id = message.from_user.id
    question_text = message.text.strip()

    if not question_text:
        await message.answer(MSG_ASK_USTAZ_WRITE_QUESTION)
        return

    data = await state.get_data()
    query_log_id = data.get("query_log_id")

    # Собираем контекст из истории
    history = await db.get_conversation_history(user_id, limit=10)
    context_parts = []
    for msg in history:
        role_label = "Пайдаланушы" if msg["role"] == "user" else "AI"
        context_parts.append(f"{role_label}: {msg['message_text'][:200]}")
    conversation_context = "\n".join(context_parts) if context_parts else None

    # Получаем AI-ответ из query_log если есть
    ai_answer_text = None
    if query_log_id:
        cursor = await db._conn.execute(
            "SELECT answer_text FROM query_logs WHERE id = ?", (query_log_id,)
        )
        row = await cursor.fetchone()
        if row:
            ai_answer_text = row["answer_text"]

    # Создаём консультацию
    consultation_id = await db.create_consultation(
        user_telegram_id=user_id,
        question_text=question_text,
        ai_answer_text=ai_answer_text,
        conversation_context=conversation_context,
        query_log_id=query_log_id,
    )

    # Увеличиваем счётчик использований
    await db.increment_ustaz_usage(user_id)

    await state.clear()
    await message.answer(MSG_ASK_USTAZ_SENT)
    logger.info(f"Consultation #{consultation_id} created by user {user_id}")

    # Уведомляем устазов (через ustaz_bot если доступен)
    ustaz_bot = kwargs.get("ustaz_bot")
    if ustaz_bot:
        ustazs = await db.get_active_ustazs()
        user = await db.get_user(user_id)
        user_name = user.get("first_name") or user.get("username") or str(user_id)
        for ustaz in ustazs:
            try:
                await ustaz_bot.send_message(
                    chat_id=ustaz["telegram_id"],
                    text=MSG_USTAZ_NEW_QUESTION.format(
                        user_name=user_name,
                        question=question_text[:200],
                    ),
                )
            except Exception as e:
                logger.warning(f"Failed to notify ustaz {ustaz['telegram_id']}: {e}")
