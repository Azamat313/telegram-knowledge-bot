"""
Точка входа: запуск пользовательского Telegram-бота с ИИ (ChatGPT) + кэшированием.
"""

import asyncio
import sys
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from aiogram.fsm.storage.memory import MemoryStorage
from loguru import logger

from config import BOT_TOKEN, LOG_PATH, OPENAI_API_KEY, MODERATOR_BOT_TOKEN
from database.db import Database
from core.search_engine import SearchEngine
from core.ai_engine import AIEngine
from core.knowledge_loader import load_all_knowledge
from core.muftyat_api import MuftyatAPI
from bot.handlers import user, admin, subscription
from bot.handlers import consultation, calendar, moderator_request
from bot.handlers import onboarding
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

    # Инициализация API muftyat.kz
    muftyat_api = MuftyatAPI()
    await muftyat_api.init()
    logger.info("MuftyatAPI initialized")

    # Инициализация поискового + кэш-движка
    search_engine = SearchEngine()
    search_engine.init()

    # Загрузка базы знаний (инкрементальная — добавляет только новые документы)
    logger.info(f"Knowledge base: {search_engine.get_collection_count()} existing documents")
    doc_count = load_all_knowledge(search_engine)
    if doc_count > 0:
        logger.info(f"Knowledge base: +{doc_count} new documents, total={search_engine.get_collection_count()}")
    else:
        logger.info(f"Knowledge base: up to date ({search_engine.get_collection_count()} documents)")

    # Инициализация ИИ-движка (ChatGPT)
    ai_engine = AIEngine()
    logger.info("AI engine ready")

    # Создание бота и диспетчера
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Moderator bot instance для нотификаций
    moderator_bot = None
    if MODERATOR_BOT_TOKEN:
        moderator_bot = Bot(
            token=MODERATOR_BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        logger.info("Moderator bot connected for notifications")

    # Регистрация middleware
    dp.message.middleware(RateLimitMiddleware())
    dp.message.middleware(SubscriptionCheckMiddleware(db))

    # Регистрация роутеров (порядок важен!)
    dp.include_router(onboarding.router)    # Онбординг — ПЕРЕД user
    dp.include_router(admin.router)
    dp.include_router(subscription.router)
    dp.include_router(consultation.router)
    dp.include_router(calendar.router)
    dp.include_router(moderator_request.router)
    dp.include_router(user.router)          # user.router — ПОСЛЕДНИМ (catch-all)

    # Передаём зависимости
    dp.workflow_data.update({
        "db": db,
        "search_engine": search_engine,
        "cache_engine": search_engine,
        "ai_engine": ai_engine,
        "moderator_bot": moderator_bot,
        "muftyat_api": muftyat_api,
    })

    # Устанавливаем меню команд
    await bot.set_my_commands([
        BotCommand(command="start", description="Бастау / Начать"),
        BotCommand(command="help", description="Анықтама / Справка"),
        BotCommand(command="stats", description="Менің статистикам / Моя статистика"),
        BotCommand(command="clear", description="Диалог тарихын тазалау / Очистить историю"),
        BotCommand(command="terms", description="Пайдалану шарттары / Условия"),
        BotCommand(command="paysupport", description="Төлем бойынша көмек / Помощь с оплатой"),
    ])

    logger.info("Bot is starting polling...")

    try:
        await dp.start_polling(bot)
    finally:
        await muftyat_api.close()
        await db.close()
        await bot.session.close()
        if moderator_bot:
            await moderator_bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
