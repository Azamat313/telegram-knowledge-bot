"""
Объединённый запуск: пользовательский бот + устаз-бот в одном процессе.
Общая БД, мгновенные перекрёстные уведомления через asyncio.gather.
"""

import asyncio
import sys
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from loguru import logger

from config import BOT_TOKEN, USTAZ_BOT_TOKEN, LOG_PATH, OPENAI_API_KEY
from database.db import Database
from core.search_engine import SearchEngine
from core.ai_engine import AIEngine
from core.knowledge_loader import load_all_knowledge

# User bot imports
from bot.handlers import user, admin, subscription
from bot.handlers import consultation
from bot.middlewares.rate_limit import RateLimitMiddleware
from bot.middlewares.subscription_check import SubscriptionCheckMiddleware

# Ustaz bot imports
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
    logger.info("Starting both bots...")

    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is not set! Check .env file.")
        sys.exit(1)

    if not USTAZ_BOT_TOKEN:
        logger.error("USTAZ_BOT_TOKEN is not set! Check .env file.")
        sys.exit(1)

    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY is not set! Check .env file.")
        sys.exit(1)

    # ── Общие зависимости ──
    db = Database()
    await db.connect()

    search_engine = SearchEngine()
    search_engine.init()

    if search_engine.get_collection_count() == 0:
        logger.info("Loading knowledge base...")
        doc_count = load_all_knowledge(search_engine)
        logger.info(f"Knowledge base: {doc_count} documents loaded")
    else:
        logger.info(f"Knowledge base: {search_engine.get_collection_count()} documents")

    ai_engine = AIEngine()
    logger.info("AI engine ready")

    # ── Пользовательский бот ──
    user_bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    user_dp = Dispatcher()

    user_dp.message.middleware(RateLimitMiddleware())
    user_dp.message.middleware(SubscriptionCheckMiddleware(db))

    user_dp.include_router(admin.router)
    user_dp.include_router(subscription.router)
    user_dp.include_router(consultation.router)
    user_dp.include_router(user.router)

    # ── Устаз-бот ──
    ustaz_bot_instance = Bot(
        token=USTAZ_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    ustaz_dp = Dispatcher()

    ustaz_dp.message.middleware(UstazAuthMiddleware(db))
    ustaz_dp.callback_query.middleware(UstazAuthMiddleware(db))

    ustaz_dp.include_router(ustaz_auth.router)
    ustaz_dp.include_router(ustaz.router)

    # ── Перекрёстные ссылки для мгновенных уведомлений ──
    user_dp.workflow_data.update({
        "db": db,
        "search_engine": search_engine,
        "cache_engine": search_engine,
        "ai_engine": ai_engine,
        "ustaz_bot": ustaz_bot_instance,  # Для уведомления устазов о новых вопросах
    })

    ustaz_dp.workflow_data.update({
        "db": db,
        "user_bot": user_bot,  # Для доставки ответов пользователям
    })

    logger.info("Both bots are starting polling...")

    try:
        await asyncio.gather(
            user_dp.start_polling(user_bot),
            ustaz_dp.start_polling(ustaz_bot_instance),
        )
    finally:
        await db.close()
        await user_bot.session.close()
        await ustaz_bot_instance.session.close()
        logger.info("Both bots stopped")


if __name__ == "__main__":
    asyncio.run(main())
