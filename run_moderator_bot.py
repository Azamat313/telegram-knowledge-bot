"""
Точка входа: запуск модератор Telegram-бота (отдельный процесс).
Использует ту же БД что и пользовательский бот.
Для доставки ответов пользователям нужен user_bot (BOT_TOKEN).
"""

import asyncio
import sys
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from loguru import logger

from config import BOT_TOKEN, MODERATOR_BOT_TOKEN, LOG_PATH
from database.db import Database
from moderator_bot.handlers import moderator


def setup_logging():
    """Настройка логирования с ротацией."""
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logger.add(
        LOG_PATH,
        rotation="10 MB",
        retention="30 days",
        compression="zip",
        level="DEBUG",
        encoding="utf-8",
    )


async def main():
    setup_logging()
    logger.info("Starting moderator bot...")

    if not MODERATOR_BOT_TOKEN:
        logger.error("MODERATOR_BOT_TOKEN is not set! Check .env file.")
        sys.exit(1)

    # Инициализация БД (общая с пользовательским ботом)
    db = Database()
    await db.connect()

    # Модератор-бот
    mod_bot = Bot(
        token=MODERATOR_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Роутеры
    dp.include_router(moderator.router)

    # User bot для доставки ответов пользователям
    user_bot = None
    if BOT_TOKEN:
        user_bot = Bot(
            token=BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        logger.info("User bot connected for answer delivery")
    else:
        logger.warning("BOT_TOKEN not set — answers won't be delivered to users")

    # Передаём зависимости
    dp.workflow_data.update({
        "db": db,
        "user_bot": user_bot,
    })

    logger.info("Moderator bot is starting polling...")

    try:
        await dp.start_polling(mod_bot)
    finally:
        await db.close()
        await mod_bot.session.close()
        if user_bot:
            await user_bot.session.close()
        logger.info("Moderator bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
