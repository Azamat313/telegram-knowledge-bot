"""
Обработчики для «Әкімшілікке жазу» — тикеты от пользователей к модераторам.
"""

from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from loguru import logger

from database.db import Database
from core.messages import get_msg

router = Router()


class ModeratorRequestStates(StatesGroup):
    waiting_for_message = State()


@router.message(F.text.in_({"📝 Әкімшілікке жазу", "📝 Написать администрации"}))
async def btn_write_admin(message: Message, db: Database, state: FSMContext, **kwargs):
    """Кнопка 'Написать администрации'."""
    user = await db.get_user(message.from_user.id)
    lang = user.get("language", "kk") if user else "kk"

    await state.set_state(ModeratorRequestStates.waiting_for_message)
    await message.answer(get_msg("mod_request_prompt", lang))


@router.message(ModeratorRequestStates.waiting_for_message, F.text)
async def on_moderator_message(message: Message, db: Database, state: FSMContext, **kwargs):
    """Пользователь написал сообщение для администрации."""
    user_id = message.from_user.id
    text = message.text.strip()

    if not text:
        return

    user = await db.get_user(user_id)
    lang = user.get("language", "kk") if user else "kk"

    # Создаём тикет
    ticket_id = await db.create_moderator_ticket(user_id, text)

    await state.clear()
    await message.answer(get_msg("mod_request_sent", lang, ticket_id=ticket_id))

    logger.info(f"Moderator ticket #{ticket_id} created by user {user_id}")

    # Уведомляем модератор-бота
    moderator_bot = kwargs.get("moderator_bot")
    if moderator_bot:
        # Получаем список админов из конфига для отправки уведомлений
        from config import ADMIN_IDS
        user_name = user.get("first_name") or user.get("username") or str(user_id)
        for admin_id in ADMIN_IDS:
            try:
                await moderator_bot.send_message(
                    chat_id=admin_id,
                    text=(
                        f"📝 Жаңа тикет #{ticket_id}\n\n"
                        f"Пайдаланушы: {user_name}\n"
                        f"Хабарлама: {text[:300]}\n\n"
                        f"/queue — кезекті көру"
                    ),
                )
            except Exception as e:
                logger.warning(f"Failed to notify admin {admin_id}: {e}")
