"""
Основные обработчики модератор-бота.
/start, /queue, приём и ответ на тикеты.
"""

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from loguru import logger

from database.db import Database
from moderator_bot.keyboards.inline import get_ticket_keyboard, get_cancel_ticket_keyboard

router = Router()


class ModAnswerStates(StatesGroup):
    waiting_for_answer = State()


@router.message(CommandStart())
async def cmd_start(message: Message, **kwargs):
    """Приветствие модератора."""
    await message.answer(
        "Ассалаумағалейкум, модератор!\n\n"
        "Бұл — техникалық қолдау панелі.\n"
        "Пайдаланушылардан келген тикеттерге жауап беруге болады.\n\n"
        "Командалар:\n"
        "/queue — кезекті көру\n"
        "/stats — статистика"
    )


@router.message(Command("queue"))
async def cmd_queue(message: Message, db: Database, **kwargs):
    """Показать очередь ожидающих тикетов."""
    tickets = await db.get_pending_tickets(limit=10)
    if not tickets:
        await message.answer("📋 Кезекте тикеттер жоқ.")
        return

    await message.answer(f"📋 Кезекте {len(tickets)} тикет бар:\n")

    for t in tickets:
        user_name = t.get("first_name") or t.get("username") or str(t["user_telegram_id"])
        text = (
            f"#{t['id']} | {user_name}\n"
            f"Хабарлама: {t['message_text'][:300]}\n"
            f"Уақыты: {t['created_at'][:16]}"
        )
        await message.answer(text, reply_markup=get_ticket_keyboard(t["id"]))


@router.message(Command("stats"))
async def cmd_stats(message: Message, db: Database, **kwargs):
    """Статистика тикетов."""
    stats = await db.get_ticket_stats()
    text = (
        f"📊 Тикет статистикасы:\n\n"
        f"Барлығы: {stats.get('total', 0)}\n"
        f"Күтуде: {stats.get('pending', 0)}\n"
        f"Жауап берілді: {stats.get('answered', 0)}"
    )
    await message.answer(text)


@router.callback_query(F.data.startswith("mod_take:"))
async def on_take_ticket(callback: CallbackQuery, db: Database, state: FSMContext, **kwargs):
    """Модератор берёт тикет."""
    ticket_id = int(callback.data.split(":")[1])

    ticket = await db.get_moderator_ticket(ticket_id)
    if not ticket or ticket["status"] != "pending":
        await callback.answer("Бұл тикет жабылған немесе табылмады.", show_alert=True)
        return

    await state.set_state(ModAnswerStates.waiting_for_answer)
    await state.update_data(ticket_id=ticket_id)

    text = (
        f"✅ Тикет #{ticket_id} қабылданды!\n\n"
        f"Хабарлама: {ticket['message_text']}\n\n"
        f"Жауабыңызды жазыңыз:"
    )
    await callback.message.edit_text(
        text,
        reply_markup=get_cancel_ticket_keyboard(ticket_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mod_skip:"))
async def on_skip_ticket(callback: CallbackQuery, **kwargs):
    """Пропуск тикета."""
    await callback.message.delete()
    await callback.answer("Тикет өткізілді")


@router.callback_query(F.data.startswith("mod_cancel:"))
async def on_cancel_ticket(callback: CallbackQuery, state: FSMContext, **kwargs):
    """Отмена ответа на тикет."""
    await state.clear()
    await callback.message.edit_text("Жауап тоқтатылды.")
    await callback.answer()


@router.message(ModAnswerStates.waiting_for_answer, F.text)
async def on_answer_text(message: Message, db: Database, state: FSMContext, **kwargs):
    """Модератор пишет ответ на тикет."""
    answer_text = message.text.strip()
    if not answer_text:
        await message.answer("Жауап мәтінін жазыңыз.")
        return

    data = await state.get_data()
    ticket_id = data.get("ticket_id")

    if not ticket_id:
        await state.clear()
        await message.answer("Қате орын алды. /queue командасын қайта жіберіңіз.")
        return

    # Сохраняем ответ
    ticket = await db.answer_ticket(ticket_id, answer_text)
    if not ticket:
        await state.clear()
        await message.answer("Тикет табылмады.")
        return

    await state.clear()
    await message.answer(f"✅ Тикет #{ticket_id} — жауап жіберілді!")
    logger.info(f"Moderator answered ticket #{ticket_id}")

    # Отправляем ответ пользователю через user_bot
    user_bot = kwargs.get("user_bot")
    if user_bot:
        try:
            user = await db.get_user(ticket["user_telegram_id"])
            lang = user.get("language", "kk") if user else "kk"

            if lang == "ru":
                text = (
                    f"Получен ответ от администрации!\n\n"
                    f"Ваше сообщение:\n{ticket['message_text'][:200]}\n\n"
                    f"Ответ:\n{answer_text}"
                )
            else:
                text = (
                    f"Әкімшіліктен жауап келді!\n\n"
                    f"Сіздің хабарламаңыз:\n{ticket['message_text'][:200]}\n\n"
                    f"Жауап:\n{answer_text}"
                )

            await user_bot.send_message(
                chat_id=ticket["user_telegram_id"],
                text=text,
            )
            logger.info(f"Ticket answer delivered to user {ticket['user_telegram_id']}")
        except Exception as e:
            logger.error(f"Failed to send ticket answer to user: {e}")
            await message.answer(
                f"⚠️ Жауап сақталды, бірақ пайдаланушыға жіберу сәтсіз: {e}"
            )
