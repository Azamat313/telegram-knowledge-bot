"""
Точка входа: запуск пользовательского Telegram-бота с ИИ (ChatGPT) + кэшированием.
"""

import asyncio
import sys
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from loguru import logger

from config import BOT_TOKEN, LOG_PATH, OPENAI_API_KEY
from database.db import Database
from core.search_engine import SearchEngine
from core.ai_engine import AIEngine
from core.knowledge_loader import load_all_knowledge
from bot.handlers import user, admin, subscription
from bot.handlers import consultation
from bot.middlewares.rate_limit import RateLimitMiddleware
from bot.middlewares.subscription_check import SubscriptionCheckMiddleware


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
    logger.info("Starting bot...")

    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is not set! Check .env file.")
        sys.exit(1)

    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY is not set! Check .env file.")
        sys.exit(1)

    # Инициализация БД
    db = Database()
    await db.connect()

    # Инициализация поискового + кэш-движка
    search_engine = SearchEngine()
    search_engine.init()

    # Загрузка базы знаний (если пустая)
    if search_engine.get_collection_count() == 0:
        logger.info("Loading knowledge base...")
        doc_count = load_all_knowledge(search_engine)
        logger.info(f"Knowledge base: {doc_count} documents loaded")
    else:
        logger.info(f"Knowledge base: {search_engine.get_collection_count()} documents")

    # Инициализация ИИ-движка (ChatGPT)
    ai_engine = AIEngine()
    logger.info("AI engine ready")

    # Создание бота и диспетчера
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Регистрация middleware
    dp.message.middleware(RateLimitMiddleware())
    dp.message.middleware(SubscriptionCheckMiddleware(db))

    # Регистрация роутеров
    dp.include_router(admin.router)
    dp.include_router(subscription.router)
    dp.include_router(consultation.router)
    dp.include_router(user.router)

    # Передаём зависимости
    dp.workflow_data.update({
        "db": db,
        "search_engine": search_engine,
        "cache_engine": search_engine,
        "ai_engine": ai_engine,
    })

    logger.info("Bot is starting polling...")

    try:
        await dp.start_polling(bot)
    finally:
        await db.close()
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
