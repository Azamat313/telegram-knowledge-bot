"""
Точка входа: запуск пользовательского Telegram-бота с ИИ (ChatGPT) + кэшированием.
"""

import asyncio
import sys
import os
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from aiogram.fsm.storage.memory import MemoryStorage
from loguru import logger

from config import BOT_TOKEN, LOG_PATH, OPENAI_API_KEY, MODERATOR_BOT_TOKEN, USTAZ_BOT_TOKEN
from database.db import Database
from core.search_engine import SearchEngine
from core.ai_engine import AIEngine
from core.knowledge_loader import load_all_knowledge
from core.muftyat_api import MuftyatAPI
from core.ramadan_calendar import is_ramadan, get_ramadan_day_number, ensure_prayer_times, RAMADAN_START, RAMADAN_END
from core.messages import get_msg
from core.daily_tips import DAILY_TIPS
from bot.handlers import user, admin, subscription
from bot.handlers import consultation, calendar, moderator_request
from bot.handlers import onboarding, kaspi_payment
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


async def ramadan_reminder_task(bot: Bot, db: Database, muftyat_api: MuftyatAPI):
    """Background task: отправка напоминаний за 10 мин до сәресі/ауызашар."""
    sent_today: set[str] = set()
    last_reset_date = datetime.now().date()

    while True:
        try:
            await asyncio.sleep(60)

            now = datetime.now()

            # Reset tracking set at midnight
            if now.date() != last_reset_date:
                sent_today.clear()
                last_reset_date = now.date()

            if not is_ramadan():
                continue

            # Get distinct coordinate groups
            groups = await db.get_users_grouped_by_coordinates()
            if not groups:
                continue

            today_str = now.strftime("%Y-%m-%d")

            for group in groups:
                lat = group["city_lat"]
                lng = group["city_lng"]
                city = group["city"] or "?"

                # Ensure prayer times are cached
                await ensure_prayer_times(muftyat_api, db, city, lat, lng)

                # Get today's prayer times
                cached = await db.get_cached_prayer_times(lat, lng, today_str, today_str)
                if not cached:
                    continue

                day_data = cached[0]
                fajr_str = day_data.get("fajr", "")
                maghrib_str = day_data.get("maghrib", "")

                if not fajr_str or not maghrib_str:
                    continue

                # Parse times
                try:
                    fajr_time = datetime.strptime(f"{today_str} {fajr_str}", "%Y-%m-%d %H:%M")
                    maghrib_time = datetime.strptime(f"{today_str} {maghrib_str}", "%Y-%m-%d %H:%M")
                except ValueError:
                    continue

                # Check suhoor reminder window: fajr - 10 min to fajr - 9 min
                suhoor_target = fajr_time - timedelta(minutes=10)
                should_send_suhoor = suhoor_target <= now < suhoor_target + timedelta(minutes=1)

                # Check iftar reminder window: maghrib - 10 min to maghrib - 9 min
                iftar_target = maghrib_time - timedelta(minutes=10)
                should_send_iftar = iftar_target <= now < iftar_target + timedelta(minutes=1)

                if not should_send_suhoor and not should_send_iftar:
                    continue

                # Get users for this coordinate group
                users = await db.get_users_by_coordinates(lat, lng)

                for u in users:
                    tid = u["telegram_id"]
                    lang = u.get("language", "kk")

                    if should_send_suhoor:
                        key = f"{today_str}:{tid}:suhoor"
                        if key not in sent_today:
                            try:
                                text = get_msg("suhoor_reminder", lang, city=city, fajr=fajr_str)
                                await bot.send_message(tid, text, parse_mode=ParseMode.HTML)
                                sent_today.add(key)
                            except Exception as e:
                                logger.debug(f"Suhoor reminder failed for {tid}: {e}")

                    if should_send_iftar:
                        key = f"{today_str}:{tid}:iftar"
                        if key not in sent_today:
                            try:
                                text = get_msg("iftar_reminder", lang, city=city, maghrib=maghrib_str)
                                await bot.send_message(tid, text, parse_mode=ParseMode.HTML)
                                sent_today.add(key)
                            except Exception as e:
                                logger.debug(f"Iftar reminder failed for {tid}: {e}")

            # ── Daily tip at 12:00 ──
            if is_ramadan() and now.hour == 12 and now.minute < 1:
                day_num = get_ramadan_day_number()
                if day_num and 1 <= day_num <= len(DAILY_TIPS):
                    tip = DAILY_TIPS[day_num - 1]
                    all_users = []
                    for group in groups:
                        users = await db.get_users_by_coordinates(group["city_lat"], group["city_lng"])
                        all_users.extend(users)
                    # Deduplicate by telegram_id
                    seen_tids: set[int] = set()
                    unique_users = []
                    for u in all_users:
                        if u["telegram_id"] not in seen_tids:
                            seen_tids.add(u["telegram_id"])
                            unique_users.append(u)
                    sent_count = 0
                    for u in unique_users:
                        tid = u["telegram_id"]
                        key = f"{today_str}:{tid}:daily_tip"
                        if key not in sent_today:
                            try:
                                await bot.send_message(tid, tip, parse_mode=ParseMode.HTML)
                                sent_today.add(key)
                                sent_count += 1
                                if sent_count % 25 == 0:
                                    await asyncio.sleep(1)
                            except Exception as e:
                                logger.debug(f"Daily tip failed for {tid}: {e}")
                    if sent_count:
                        logger.info(f"Daily tip #{day_num} sent to {sent_count} users")

        except asyncio.CancelledError:
            logger.info("Ramadan reminder task cancelled")
            break
        except Exception as e:
            logger.error(f"Ramadan reminder task error: {e}")
            await asyncio.sleep(60)


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

    # Ustaz bot instance для нотификаций устазам
    ustaz_bot_notifier = None
    if USTAZ_BOT_TOKEN:
        ustaz_bot_notifier = Bot(
            token=USTAZ_BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        logger.info("Ustaz bot connected for notifications")

    # Регистрация middleware
    dp.message.middleware(RateLimitMiddleware())
    dp.message.middleware(SubscriptionCheckMiddleware(db))

    # Регистрация роутеров (порядок важен!)
    dp.include_router(onboarding.router)    # Онбординг — ПЕРЕД user
    dp.include_router(admin.router)
    dp.include_router(subscription.router)
    dp.include_router(kaspi_payment.router)
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
        "ustaz_bot": ustaz_bot_notifier,
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

    # Start Ramadan reminder background task
    reminder_task = asyncio.create_task(
        ramadan_reminder_task(bot, db, muftyat_api)
    )
    logger.info("Ramadan reminder task started")

    try:
        await dp.start_polling(bot)
    finally:
        reminder_task.cancel()
        try:
            await reminder_task
        except asyncio.CancelledError:
            pass
        await muftyat_api.close()
        await db.close()
        await bot.session.close()
        if moderator_bot:
            await moderator_bot.session.close()
        if ustaz_bot_notifier:
            await ustaz_bot_notifier.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
