"""
Основные обработчики устаз-бота.
/start, /queue, /mystats, приём и ответ на вопросы.
Показываем ТОЛЬКО вопрос (без истории, без AI-ответа).
"""

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from loguru import logger

from config import (
    MSG_USTAZ_WELCOME,
    MSG_USTAZ_QUEUE_EMPTY,
    MSG_USTAZ_QUESTION_TAKEN,
    MSG_USTAZ_QUESTION_ALREADY_TAKEN,
    MSG_USTAZ_ANSWER_SENT,
    MSG_USTAZ_HAS_ACTIVE,
    MSG_CONSULTATION_ANSWER,
)
from database.db import Database
from ustaz_bot.keyboards.inline import get_queue_item_keyboard, get_cancel_answer_keyboard

router = Router()


class AnswerStates(StatesGroup):
    waiting_for_answer = State()


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database, **kwargs):
    """Приветствие устаза."""
    ustaz = await db.get_ustaz(message.from_user.id)
    if ustaz:
        await message.answer(MSG_USTAZ_WELCOME)
    else:
        await message.answer(
            "Ассалаумағалейкум! Сіз устаз ретінде тіркелмегенсіз.\n"
            "Әкімшіге хабарласыңыз."
        )


@router.message(Command("queue"))
async def cmd_queue(message: Message, db: Database, **kwargs):
    """Показать очередь ожидающих вопросов (только вопрос, без истории/AI)."""
    # Проверяем, нет ли у устаза активного вопроса
    active = await db.get_ustaz_in_progress(message.from_user.id)
    if active:
        await message.answer(
            f"{MSG_USTAZ_HAS_ACTIVE}\n\n"
            f"Сұрақ: {active['question_text'][:300]}\n\n"
            f"Жауабыңызды жазыңыз немесе /cancel_answer — болдырмау."
        )
        return

    consultations = await db.get_pending_consultations(limit=10)
    if not consultations:
        await message.answer(MSG_USTAZ_QUEUE_EMPTY)
        return

    await message.answer(f"📋 Кезекте {len(consultations)} сұрақ бар:\n")

    for c in consultations:
        user_name = c.get("first_name") or c.get("username") or str(c["user_telegram_id"])
        text = (
            f"#{c['id']} | {user_name}\n"
            f"Сұрақ: {c['question_text'][:300]}\n"
        )
        await message.answer(text, reply_markup=get_queue_item_keyboard(c["id"]))


@router.message(Command("mystats"))
async def cmd_mystats(message: Message, db: Database, **kwargs):
    """Статистика устаза."""
    ustaz = kwargs.get("ustaz")
    if not ustaz:
        ustaz = await db.get_ustaz(message.from_user.id)

    if not ustaz:
        await message.answer("Профиль табылмады.")
        return

    text = (
        f"📊 Менің статистикам:\n\n"
        f"Жалпы жауаптар: {ustaz['total_answered']}\n"
        f"Статус: {'Белсенді' if ustaz['is_active'] else 'Белсенді емес'}\n"
        f"Тіркелген: {ustaz['created_at'][:10]}"
    )
    await message.answer(text)


@router.callback_query(F.data.startswith("take:"))
async def on_take_question(callback: CallbackQuery, db: Database, state: FSMContext, **kwargs):
    """Устаз берёт вопрос из очереди."""
    consultation_id = int(callback.data.split(":")[1])
    ustaz_id = callback.from_user.id

    # Проверяем, нет ли уже активного вопроса
    active = await db.get_ustaz_in_progress(ustaz_id)
    if active:
        await callback.answer(MSG_USTAZ_HAS_ACTIVE, show_alert=True)
        return

    # Берём вопрос
    taken = await db.take_consultation(consultation_id, ustaz_id)
    if not taken:
        await callback.answer(MSG_USTAZ_QUESTION_ALREADY_TAKEN, show_alert=True)
        return

    consultation = await db.get_consultation(consultation_id)

    # Показываем только вопрос
    text = (
        f"✅ Сұрақ #{consultation_id} қабылданды!\n\n"
        f"Сұрақ: {consultation['question_text']}\n\n"
        f"{MSG_USTAZ_QUESTION_TAKEN}"
    )

    await state.set_state(AnswerStates.waiting_for_answer)
    await state.update_data(consultation_id=consultation_id)

    await callback.message.edit_text(
        text,
        reply_markup=get_cancel_answer_keyboard(consultation_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("skip:"))
async def on_skip_question(callback: CallbackQuery, **kwargs):
    """Устаз пропускает вопрос."""
    await callback.message.delete()
    await callback.answer("Сұрақ өткізілді")


@router.callback_query(F.data.startswith("cancel_answer:"))
async def on_cancel_answer(callback: CallbackQuery, db: Database, state: FSMContext, **kwargs):
    """Устаз отменяет ответ — вопрос возвращается в очередь."""
    consultation_id = int(callback.data.split(":")[1])

    # Возвращаем вопрос в pending
    await db._conn.execute(
        "UPDATE consultations SET ustaz_telegram_id = NULL, status = 'pending', "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (consultation_id,),
    )
    await db._conn.commit()

    await state.clear()
    await callback.message.edit_text("Сұрақ кезекке қайтарылды.")
    await callback.answer()


@router.message(Command("cancel_answer"))
async def cmd_cancel_answer(message: Message, db: Database, state: FSMContext, **kwargs):
    """Отмена ответа через команду."""
    active = await db.get_ustaz_in_progress(message.from_user.id)
    if active:
        await db._conn.execute(
            "UPDATE consultations SET ustaz_telegram_id = NULL, status = 'pending', "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (active["id"],),
        )
        await db._conn.commit()
        await state.clear()
        await message.answer("Сұрақ кезекке қайтарылды.")
    else:
        await message.answer("Сізде белсенді сұрақ жоқ.")


@router.message(AnswerStates.waiting_for_answer, F.text)
async def on_answer_text(message: Message, db: Database, state: FSMContext, **kwargs):
    """Устаз пишет ответ."""
    answer_text = message.text.strip()
    if not answer_text:
        await message.answer("Жауап мәтінін жазыңыз.")
        return

    if len(answer_text) > 3500:
        await message.answer(
            f"Жауап тым ұзын ({len(answer_text)} символ). "
            f"Максимум — 3500 символ. Қысқартып қайта жіберіңіз."
        )
        return

    data = await state.get_data()
    consultation_id = data.get("consultation_id")

    if not consultation_id:
        await state.clear()
        await message.answer("Қате орын алды. /queue командасын қайта жіберіңіз.")
        return

    # Сохраняем ответ
    consultation = await db.answer_consultation(consultation_id, answer_text)
    if not consultation:
        await state.clear()
        await message.answer("Консультация табылмады.")
        return

    # Обновляем статистику устаза
    await db.update_ustaz_stats(message.from_user.id)

    await state.clear()
    await message.answer(MSG_USTAZ_ANSWER_SENT)
    logger.info(
        f"Ustaz {message.from_user.id} answered consultation #{consultation_id}"
    )

    # Отправляем ответ пользователю через user_bot
    user_bot = kwargs.get("user_bot")
    if user_bot:
        try:
            await user_bot.send_message(
                chat_id=consultation["user_telegram_id"],
                text=MSG_CONSULTATION_ANSWER.format(
                    question=consultation["question_text"][:200],
                    answer=answer_text,
                ),
            )
            logger.info(
                f"Answer delivered to user {consultation['user_telegram_id']}"
            )
        except Exception as e:
            logger.error(f"Failed to send answer to user: {e}")
            await message.answer(
                f"⚠️ Жауап сақталды, бірақ пайдаланушыға жіберу сәтсіз аяқталды: {e}"
            )
