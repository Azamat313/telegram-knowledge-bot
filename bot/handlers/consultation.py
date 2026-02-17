"""
Обработчики консультаций с устазом (пользовательская сторона).
Новый flow: кнопка → ввод вопроса → подтверждение → отправка.
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from loguru import logger

from config import MSG_USTAZ_NEW_QUESTION
from database.db import Database
from core.messages import get_msg

router = Router()


class ConsultationStates(StatesGroup):
    waiting_for_question = State()
    confirming_question = State()


def _get_confirm_keyboard(lang: str = "kk") -> InlineKeyboardMarkup:
    """Клавиатура подтверждения вопроса."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=get_msg("ask_ustaz_confirm_yes", lang),
                callback_data="confirm_ustaz_yes",
            ),
            InlineKeyboardButton(
                text=get_msg("ask_ustaz_confirm_no", lang),
                callback_data="confirm_ustaz_no",
            ),
        ],
    ])


# Кнопка из главной клавиатуры (reply keyboard)
@router.message(F.text.in_({"🕌 Ұстазға сұрақ", "🕌 Вопрос устазу"}))
async def btn_ask_ustaz(message: Message, db: Database, state: FSMContext, **kwargs):
    """Кнопка 'Устазға сұрақ' из главной клавиатуры."""
    user = await db.get_user(message.from_user.id)
    lang = user.get("language", "kk") if user else "kk"

    await state.set_state(ConsultationStates.waiting_for_question)
    await state.update_data(query_log_id=None)
    await message.answer(get_msg("ask_ustaz_prompt", lang))


# Inline-кнопка под AI-ответом
@router.callback_query(F.data.startswith("ask_ustaz:"))
async def on_ask_ustaz_button(callback: CallbackQuery, db: Database, state: FSMContext, **kwargs):
    """Пользователь нажал 'Устазға сұрақ' под ответом."""
    user = await db.get_user(callback.from_user.id)
    lang = user.get("language", "kk") if user else "kk"

    query_log_id = int(callback.data.split(":")[1])

    await state.set_state(ConsultationStates.waiting_for_question)
    await state.update_data(query_log_id=query_log_id)

    await callback.message.answer(get_msg("ask_ustaz_prompt", lang))
    await callback.answer()


@router.message(ConsultationStates.waiting_for_question, F.text)
async def on_question_text(message: Message, db: Database, state: FSMContext, **kwargs):
    """Пользователь ввёл текст вопроса — показываем подтверждение."""
    question_text = message.text.strip()
    if not question_text:
        return

    user = await db.get_user(message.from_user.id)
    lang = user.get("language", "kk") if user else "kk"

    # Формируем тему (первое предложение, до 60 символов)
    subject = question_text.split(".")[0].split("?")[0].split("!")[0][:60]
    if len(subject) < len(question_text):
        subject += "..."

    await state.update_data(question_text=question_text, subject=subject)
    await state.set_state(ConsultationStates.confirming_question)

    await message.answer(
        get_msg("ask_ustaz_confirm", lang, subject=subject, question=question_text),
        reply_markup=_get_confirm_keyboard(lang),
    )


@router.callback_query(F.data == "confirm_ustaz_yes", ConsultationStates.confirming_question)
async def on_confirm_yes(callback: CallbackQuery, db: Database, state: FSMContext, **kwargs):
    """Пользователь подтвердил отправку вопроса."""
    user_id = callback.from_user.id
    data = await state.get_data()
    question_text = data.get("question_text", "")
    query_log_id = data.get("query_log_id")

    user = await db.get_user(user_id)
    lang = user.get("language", "kk") if user else "kk"

    # Создаём консультацию
    consultation_id = await db.create_consultation(
        user_telegram_id=user_id,
        question_text=question_text,
        query_log_id=query_log_id,
    )

    await state.clear()

    first_name = callback.from_user.first_name or ""
    username = f"@{callback.from_user.username}" if callback.from_user.username else ""

    await callback.message.edit_text(
        get_msg("ask_ustaz_sent", lang,
                first_name=first_name,
                username=username,
                ticket_id=consultation_id),
    )
    await callback.answer()
    logger.info(f"Consultation #{consultation_id} created by user {user_id}")

    # Уведомляем устазов
    ustaz_bot = kwargs.get("ustaz_bot")
    if ustaz_bot:
        ustazs = await db.get_active_ustazs()
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


@router.callback_query(F.data == "confirm_ustaz_no", ConsultationStates.confirming_question)
async def on_confirm_no(callback: CallbackQuery, db: Database, state: FSMContext, **kwargs):
    """Пользователь отменил отправку."""
    user = await db.get_user(callback.from_user.id)
    lang = user.get("language", "kk") if user else "kk"

    await state.clear()
    await callback.message.edit_text(get_msg("ask_ustaz_cancelled", lang))
    await callback.answer()


@router.callback_query(F.data == "cancel_ustaz")
async def on_cancel_ustaz(callback: CallbackQuery, state: FSMContext, db: Database, **kwargs):
    """Отмена отправки вопроса устазу (legacy)."""
    user = await db.get_user(callback.from_user.id)
    lang = user.get("language", "kk") if user else "kk"

    await state.clear()
    await callback.message.edit_text(get_msg("ask_ustaz_cancelled", lang))
    await callback.answer()
