"""
Точка входа: запуск устаз Telegram-бота (отдельный процесс).
Использует ту же БД что и пользовательский бот.
Для доставки ответов пользователям нужен user_bot (BOT_TOKEN).
"""

import asyncio
import sys
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from loguru import logger

from config import BOT_TOKEN, USTAZ_BOT_TOKEN, LOG_PATH
from database.db import Database
from ustaz_bot.handlers import ustaz, auth as ustaz_auth
from ustaz_bot.middlewares.ustaz_auth import UstazAuthMiddleware


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
    logger.info("Starting ustaz bot...")

    if not USTAZ_BOT_TOKEN:
        logger.error("USTAZ_BOT_TOKEN is not set! Check .env file.")
        sys.exit(1)

    # Инициализация БД (общая с пользовательским ботом)
    db = Database()
    await db.connect()

    # Устаз-бот
    ustaz_bot = Bot(
        token=USTAZ_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Middleware авторизации
    dp.message.middleware(UstazAuthMiddleware(db))
    dp.callback_query.middleware(UstazAuthMiddleware(db))

    # Роутеры
    dp.include_router(ustaz_auth.router)
    dp.include_router(ustaz.router)

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

    logger.info("Ustaz bot is starting polling...")

    try:
        await dp.start_polling(ustaz_bot)
    finally:
        await db.close()
        await ustaz_bot.session.close()
        if user_bot:
            await user_bot.session.close()
        logger.info("Ustaz bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
