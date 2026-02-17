"""
Регистрация устазов.
Устаз регистрируется автоматически при /start, если его telegram_id
есть в базе ustaz_profiles (добавлен админом).
"""

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from loguru import logger

from config import MSG_USTAZ_WELCOME, MSG_USTAZ_NOT_REGISTERED
from database.db import Database

router = Router()


@router.message(CommandStart())
async def cmd_start_auth(message: Message, db: Database, **kwargs):
    """Проверка регистрации устаза при /start."""
    ustaz = await db.get_ustaz(message.from_user.id)

    if ustaz and ustaz.get("is_active"):
        # Обновляем данные если изменились
        if (message.from_user.username != ustaz.get("username") or
                message.from_user.first_name != ustaz.get("first_name")):
            await db._conn.execute(
                "UPDATE ustaz_profiles SET username = ?, first_name = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
                (message.from_user.username, message.from_user.first_name, message.from_user.id),
            )
            await db._conn.commit()
        await message.answer(MSG_USTAZ_WELCOME)
    else:
        await message.answer(MSG_USTAZ_NOT_REGISTERED)
