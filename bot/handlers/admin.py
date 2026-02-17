"""
Обработчики админ-команд.
"""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from loguru import logger

from config import ADMIN_IDS, MSG_ADMIN_ONLY
from core.search_engine import CacheEngine, SearchEngine
from core.knowledge_loader import load_all_knowledge
from database.db import Database

router = Router()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


@router.message(Command("admin_stats"))
async def cmd_admin_stats(message: Message, db: Database, cache_engine: CacheEngine, **kwargs):
    """Общая статистика бота (только для админов)."""
    if not is_admin(message.from_user.id):
        await message.answer(MSG_ADMIN_ONLY)
        return

    total_users = await db.get_total_users()
    total_queries = await db.get_total_queries()
    answered = await db.get_answered_queries()
    subscribed = await db.get_subscribed_users()
    top_questions = await db.get_top_questions(5)
    top_unanswered = await db.get_top_unanswered(5)
    cache_count = cache_engine.get_cache_count()

    text = (
        f"Статистика бота:\n\n"
        f"Пользователей: {total_users}\n"
        f"С подпиской: {subscribed}\n"
        f"Всего запросов: {total_queries}\n"
        f"Отвечено: {answered}\n"
        f"Без ответа: {total_queries - answered}\n"
        f"Кэш (ИИ-ответы): {cache_count}\n"
    )

    if top_questions:
        text += "\nТоп вопросов:\n"
        for i, q in enumerate(top_questions, 1):
            question = q["matched_question"][:60]
            text += f"  {i}. {question}... ({q['cnt']})\n"

    if top_unanswered:
        text += "\nТоп неотвеченных:\n"
        for i, q in enumerate(top_unanswered, 1):
            question = q["query_text"][:60]
            text += f"  {i}. {question}... ({q['cnt']})\n"

    await message.answer(text)
    logger.info(f"Admin stats requested by {message.from_user.id}")


@router.message(Command("admin_grant"))
async def cmd_admin_grant(message: Message, db: Database, **kwargs):
    """Выдать подписку пользователю: /admin_grant {user_id}"""
    if not is_admin(message.from_user.id):
        await message.answer(MSG_ADMIN_ONLY)
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: /admin_grant {user_id}")
        return

    try:
        target_user_id = int(parts[1])
    except ValueError:
        await message.answer("Некорректный user_id. Укажите числовой ID.")
        return

    user = await db.get_user(target_user_id)
    if not user:
        await message.answer(f"Пользователь {target_user_id} не найден в базе.")
        return

    await db.grant_subscription(target_user_id, plan_name="admin_grant", days=30)
    await message.answer(f"Подписка на 30 дней выдана пользователю {target_user_id}.")
    logger.info(
        f"Admin {message.from_user.id} granted subscription to {target_user_id}"
    )


@router.message(Command("admin_revoke"))
async def cmd_admin_revoke(message: Message, db: Database, **kwargs):
    """Снять подписку: /admin_revoke {user_id}"""
    if not is_admin(message.from_user.id):
        await message.answer(MSG_ADMIN_ONLY)
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: /admin_revoke {user_id}")
        return

    try:
        target_user_id = int(parts[1])
    except ValueError:
        await message.answer("Некорректный user_id. Укажите числовой ID.")
        return

    user = await db.get_user(target_user_id)
    if not user:
        await message.answer(f"Пользователь {target_user_id} не найден в базе.")
        return

    await db.revoke_subscription(target_user_id)
    await message.answer(f"Подписка снята у пользователя {target_user_id}.")
    logger.info(
        f"Admin {message.from_user.id} revoked subscription from {target_user_id}"
    )


@router.message(Command("admin_clear_cache"))
async def cmd_admin_clear_cache(
    message: Message, cache_engine: CacheEngine, **kwargs
):
    """Очистить кэш ИИ-ответов: /admin_clear_cache"""
    if not is_admin(message.from_user.id):
        await message.answer(MSG_ADMIN_ONLY)
        return

    cache_engine.clear_cache()
    await message.answer("Кэш ИИ-ответов очищен.")
    logger.info(f"Cache cleared by admin {message.from_user.id}")


@router.message(Command("admin_reload_knowledge"))
async def cmd_admin_reload_knowledge(
    message: Message, search_engine: SearchEngine, **kwargs
):
    """Перезагрузить базу знаний: /admin_reload_knowledge"""
    if not is_admin(message.from_user.id):
        await message.answer(MSG_ADMIN_ONLY)
        return

    await message.answer("🔄 Сбрасываю базу знаний и загружаю заново...")
    search_engine.reset_knowledge()
    doc_count = load_all_knowledge(search_engine)
    total = search_engine.get_collection_count()
    await message.answer(
        f"✅ База знаний перезагружена!\n"
        f"Загружено: {doc_count} документов\n"
        f"Всего в базе: {total}"
    )
    logger.info(f"Knowledge reloaded by admin {message.from_user.id}: {doc_count} docs")


@router.message(Command("admin_add_ustaz"))
async def cmd_admin_add_ustaz(message: Message, db: Database, **kwargs):
    """Добавить устаза: /admin_add_ustaz {telegram_id} [имя]"""
    if not is_admin(message.from_user.id):
        await message.answer(MSG_ADMIN_ONLY)
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 2:
        await message.answer("Использование: /admin_add_ustaz {telegram_id} [имя]")
        return

    try:
        ustaz_id = int(parts[1])
    except ValueError:
        await message.answer("Некорректный telegram_id. Укажите числовой ID.")
        return

    first_name = parts[2] if len(parts) > 2 else None

    # Проверяем, не добавлен ли уже
    existing = await db.get_ustaz(ustaz_id)
    if existing and existing.get("is_active"):
        await message.answer(f"Устаз {ustaz_id} уже зарегистрирован.")
        return

    if existing and not existing.get("is_active"):
        # Реактивация
        await db._conn.execute(
            "UPDATE ustaz_profiles SET is_active = TRUE, updated_at = CURRENT_TIMESTAMP "
            "WHERE telegram_id = ?",
            (ustaz_id,),
        )
        await db._conn.commit()
        await message.answer(f"Устаз {ustaz_id} реактивирован.")
    else:
        await db.add_ustaz(ustaz_id, first_name=first_name)
        await message.answer(f"Устаз {ustaz_id} добавлен.")

    logger.info(f"Admin {message.from_user.id} added ustaz {ustaz_id}")


@router.message(Command("admin_remove_ustaz"))
async def cmd_admin_remove_ustaz(message: Message, db: Database, **kwargs):
    """Удалить устаза: /admin_remove_ustaz {telegram_id}"""
    if not is_admin(message.from_user.id):
        await message.answer(MSG_ADMIN_ONLY)
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: /admin_remove_ustaz {telegram_id}")
        return

    try:
        ustaz_id = int(parts[1])
    except ValueError:
        await message.answer("Некорректный telegram_id. Укажите числовой ID.")
        return

    removed = await db.remove_ustaz(ustaz_id)
    if removed:
        await message.answer(f"Устаз {ustaz_id} деактивирован.")
    else:
        await message.answer(f"Устаз {ustaz_id} не найден.")

    logger.info(f"Admin {message.from_user.id} removed ustaz {ustaz_id}")


@router.message(Command("admin_consultation_stats"))
async def cmd_admin_consultation_stats(message: Message, db: Database, **kwargs):
    """Статистика консультаций: /admin_consultation_stats"""
    if not is_admin(message.from_user.id):
        await message.answer(MSG_ADMIN_ONLY)
        return

    stats = await db.get_consultation_stats()
    ustazs = await db.get_active_ustazs()

    text = (
        f"📊 Статистика консультаций:\n\n"
        f"Всего обращений: {stats['total']}\n"
        f"В ожидании: {stats['pending']}\n"
        f"В работе: {stats['in_progress']}\n"
        f"Отвечено: {stats['answered']}\n\n"
        f"Активных устазов: {len(ustazs)}\n"
    )

    if ustazs:
        text += "\nУстазы:\n"
        for u in ustazs:
            name = u.get("first_name") or u.get("username") or str(u["telegram_id"])
            text += f"  • {name} — {u['total_answered']} ответов\n"

    await message.answer(text)
    logger.info(f"Consultation stats requested by {message.from_user.id}")
