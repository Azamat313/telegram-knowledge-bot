"""
Обработчики пользовательских команд и сообщений.
Архитектура: Кэш → Поиск контекста → ChatGPT ИИ (с памятью) → Кэширование.
"""

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from loguru import logger

from config import (
    MSG_WELCOME, MSG_HELP, MSG_NOT_FOUND, MSG_NON_TEXT,
    MSG_WARNING, MSG_AI_ERROR, FREE_ANSWERS_LIMIT, WARNING_AT,
    MSG_HISTORY_CLEARED, MSG_ASK_USTAZ_BUTTON,
    MSG_TERMS, MSG_PAYSUPPORT,
)
from core.normalizer import normalize_text
from core.search_engine import SearchEngine
from core.ai_engine import AIEngine
from database.db import Database
from bot.keyboards.inline import get_ask_ustaz_keyboard

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database, **kwargs):
    await db.get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )
    await message.answer(MSG_WELCOME)


@router.message(Command("help"))
async def cmd_help(message: Message, **kwargs):
    await message.answer(MSG_HELP)


@router.message(Command("clear"))
async def cmd_clear(message: Message, db: Database, **kwargs):
    """Очистить историю диалога."""
    await db.clear_conversation_history(message.from_user.id)
    await message.answer(MSG_HISTORY_CLEARED)


@router.message(Command("terms"))
async def cmd_terms(message: Message, **kwargs):
    """Условия использования (обязательно для Telegram Payments)."""
    await message.answer(MSG_TERMS)


@router.message(Command("paysupport"))
async def cmd_paysupport(message: Message, **kwargs):
    """Поддержка по оплате (обязательно для Telegram Payments)."""
    await message.answer(MSG_PAYSUPPORT)


@router.message(Command("stats"))
async def cmd_stats(message: Message, db: Database, search_engine: SearchEngine, **kwargs):
    user = await db.get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )
    is_subscribed = await db.check_subscription(message.from_user.id)
    expires = user.get("subscription_expires_at", "—")
    status = "Белсенді" if is_subscribed else "Жоқ"
    if is_subscribed and expires:
        status = f"Белсенді ({expires[:10]} дейін)"

    text = (
        f"📊 Сіздің статистикаңыз:\n\n"
        f"Пайдаланылған жауаптар: {user['answers_count']}\n"
        f"Тегін лимит: {FREE_ANSWERS_LIMIT}\n"
        f"Жазылым: {status}\n"
        f"База: {search_engine.get_collection_count()} жазба\n"
        f"Кэш: {search_engine.get_cache_count()} жауап"
    )
    await message.answer(text)


@router.message(F.content_type != "text")
async def handle_non_text(message: Message, **kwargs):
    await message.answer(MSG_NON_TEXT)


@router.message(F.text)
async def handle_text_message(
    message: Message,
    db: Database,
    search_engine: SearchEngine,
    ai_engine: AIEngine,
    **kwargs,
):
    """Кэш → Контекст из базы → ChatGPT (с памятью) → Кэш."""
    user_id = message.from_user.id
    original_text = message.text.strip()

    normalized = normalize_text(original_text)
    if not normalized:
        await message.answer(MSG_NON_TEXT)
        return

    logger.info(f"Query from {user_id}: '{original_text[:80]}'")

    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")

    is_subscribed = kwargs.get("is_subscribed", False)

    # Загружаем историю диалога
    conversation_history = await db.get_conversation_history(user_id)

    # 1. Проверяем кэш (только если нет истории — иначе контекст диалога теряется)
    if not conversation_history:
        cached = await search_engine.search_cache(normalized)
        if cached:
            answer = cached["answer"]
            sources = cached.get("sources", "")

            log_id = await db.log_query(
                user_telegram_id=user_id, query_text=original_text,
                normalized_text=normalized, matched_question=cached.get("cached_question", ""),
                answer_text=answer, similarity_score=cached["similarity"], was_answered=True,
            )
            new_count = await db.increment_answers_count(user_id)

            # Сохраняем в историю
            await db.add_conversation_message(user_id, "user", original_text)
            await db.add_conversation_message(user_id, "assistant", answer)

            response_text = answer
            if sources:
                response_text += f"\n\n📚 {sources}"

            if not is_subscribed and WARNING_AT <= new_count < FREE_ANSWERS_LIMIT:
                remaining = FREE_ANSWERS_LIMIT - new_count
                response_text += f"\n\n⚠️ {MSG_WARNING.format(remaining=remaining, limit=FREE_ANSWERS_LIMIT)}"

            # Кнопка "Устазға сұрақ" для подписчиков
            reply_markup = get_ask_ustaz_keyboard(log_id) if is_subscribed else None
            await message.answer(response_text, reply_markup=reply_markup)
            logger.info(f"Cache hit for {user_id}, sim={cached['similarity']:.4f}")
            return

    # 2. Ищем контекст в базе знаний
    context_results = await search_engine.search_context(normalized, n_results=5)

    # 3. Отправляем в ChatGPT с историей
    if not ai_engine.is_available():
        await message.answer(MSG_AI_ERROR)
        return

    ai_result = await ai_engine.ask(original_text, context_results, conversation_history)

    if not ai_result.get("answer"):
        await db.log_query(
            user_telegram_id=user_id, query_text=original_text,
            normalized_text=normalized, similarity_score=0.0, was_answered=False,
        )
        await message.answer(MSG_NOT_FOUND)
        return

    answer = ai_result["answer"]
    sources_list = ai_result.get("sources", [])
    sources_str = ", ".join(sources_list) if sources_list else ""

    # 4. Кэшируем (только если нет активной истории)
    if not conversation_history:
        await search_engine.cache_answer(question=normalized, answer=answer, sources=sources_str)

    log_id = await db.log_query(
        user_telegram_id=user_id, query_text=original_text,
        normalized_text=normalized, matched_question="[AI generated]",
        answer_text=answer, similarity_score=1.0, was_answered=True,
    )
    new_count = await db.increment_answers_count(user_id)

    # Сохраняем в историю
    await db.add_conversation_message(user_id, "user", original_text)
    await db.add_conversation_message(user_id, "assistant", answer)

    response_text = answer
    if sources_str:
        response_text += f"\n\n📚 Дереккөз: {sources_str}"

    if not is_subscribed and WARNING_AT <= new_count < FREE_ANSWERS_LIMIT:
        remaining = FREE_ANSWERS_LIMIT - new_count
        response_text += f"\n\n⚠️ {MSG_WARNING.format(remaining=remaining, limit=FREE_ANSWERS_LIMIT)}"

    # Кнопка "Устазға сұрақ" для подписчиков
    reply_markup = get_ask_ustaz_keyboard(log_id) if is_subscribed else None
    await message.answer(response_text, reply_markup=reply_markup)
    logger.info(f"AI answer for {user_id}, sources={sources_list}")
