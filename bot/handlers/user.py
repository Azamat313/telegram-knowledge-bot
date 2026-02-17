"""
Обработчики пользовательских команд и сообщений.
Архитектура: Кэш → Поиск контекста → ChatGPT ИИ (с памятью) → Кэширование.
"""

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from loguru import logger

from config import (
    MSG_WELCOME, MSG_HELP, MSG_NOT_FOUND, MSG_NON_TEXT,
    MSG_WARNING, MSG_AI_ERROR, FREE_ANSWERS_LIMIT, WARNING_AT,
    MSG_HISTORY_CLEARED, MSG_TERMS, MSG_PAYSUPPORT,
)
from core.messages import get_msg
from core.normalizer import normalize_text
from core.search_engine import SearchEngine
from core.ai_engine import AIEngine
from database.db import Database
from bot.keyboards.inline import get_answer_keyboard

router = Router()


def get_main_keyboard(lang: str = "kk") -> ReplyKeyboardMarkup:
    """Главная клавиатура на нужном языке."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=get_msg("btn_calendar", lang)),
                KeyboardButton(text=get_msg("btn_ask_ustaz", lang)),
            ],
            [
                KeyboardButton(text=get_msg("btn_stats", lang)),
                KeyboardButton(text=get_msg("btn_write_admin", lang)),
            ],
            [
                KeyboardButton(text=get_msg("btn_help", lang)),
                KeyboardButton(text=get_msg("btn_terms", lang)),
            ],
        ],
        resize_keyboard=True,
    )


# /start теперь в onboarding.py


@router.message(Command("help"))
async def cmd_help(message: Message, db: Database, **kwargs):
    user = await db.get_user(message.from_user.id)
    lang = user.get("language", "kk") if user else "kk"
    await message.answer(get_msg("help", lang))


@router.message(Command("clear"))
async def cmd_clear(message: Message, db: Database, **kwargs):
    """Очистить историю диалога."""
    user = await db.get_user(message.from_user.id)
    lang = user.get("language", "kk") if user else "kk"
    await db.clear_conversation_history(message.from_user.id)
    await message.answer(get_msg("history_cleared", lang))


@router.message(Command("terms"))
async def cmd_terms(message: Message, db: Database, **kwargs):
    """Условия использования (обязательно для Telegram Payments)."""
    user = await db.get_user(message.from_user.id)
    lang = user.get("language", "kk") if user else "kk"
    await message.answer(get_msg("terms", lang))


@router.message(Command("paysupport"))
async def cmd_paysupport(message: Message, db: Database, **kwargs):
    """Поддержка по оплате (обязательно для Telegram Payments)."""
    user = await db.get_user(message.from_user.id)
    lang = user.get("language", "kk") if user else "kk"
    await message.answer(get_msg("paysupport", lang))


@router.message(Command("stats"))
async def cmd_stats(message: Message, db: Database, search_engine: SearchEngine, **kwargs):
    user = await db.get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )
    lang = user.get("language", "kk")
    is_subscribed = await db.check_subscription(message.from_user.id)
    expires = user.get("subscription_expires_at", "—")

    if is_subscribed and expires:
        sub_status = get_msg("subscription_status_active", lang, expires=expires[:10])
    else:
        sub_status = get_msg("subscription_status_inactive", lang)

    text = get_msg("stats", lang,
                   answers_count=user['answers_count'],
                   free_limit=FREE_ANSWERS_LIMIT,
                   subscription_status=sub_status,
                   kb_count=search_engine.get_collection_count(),
                   cache_count=search_engine.get_cache_count())
    await message.answer(text)


# Кнопки обоих языков — Статистика
@router.message(F.text.in_({"📊 Статистика"}))
async def btn_stats(message: Message, db: Database, search_engine: SearchEngine, **kwargs):
    await cmd_stats(message, db=db, search_engine=search_engine, **kwargs)


# Кнопки обоих языков — Анықтама / Справка
@router.message(F.text.in_({"❓ Анықтама", "❓ Справка"}))
async def btn_help(message: Message, db: Database, **kwargs):
    await cmd_help(message, db=db, **kwargs)


# Кнопки обоих языков — Шарттар / Условия
@router.message(F.text.in_({"📜 Шарттар", "📜 Условия"}))
async def btn_terms(message: Message, db: Database, **kwargs):
    await cmd_terms(message, db=db, **kwargs)


@router.callback_query(F.data.startswith("suggest:"))
async def on_suggestion_click(
    callback: CallbackQuery, db: Database,
    search_engine: SearchEngine, ai_engine: AIEngine, **kwargs
):
    """Пользователь нажал на кнопку-предложение — обрабатываем как вопрос."""
    btn_rows = callback.message.reply_markup.inline_keyboard
    idx = int(callback.data.split(":")[1])

    suggestion_text = None
    if idx < len(btn_rows):
        raw = btn_rows[idx][0].text
        suggestion_text = raw.lstrip("💡").strip()
        if suggestion_text.endswith("..."):
            suggestion_text = None

    await callback.answer()

    if not suggestion_text:
        return

    # Отправляем вопрос как сообщение и обрабатываем
    fake_msg = await callback.message.answer(f"💬 {suggestion_text}")
    await _process_question(fake_msg, db, search_engine, ai_engine, suggestion_text, **kwargs)


@router.message(F.content_type != "text")
async def handle_non_text(message: Message, db: Database, **kwargs):
    user = await db.get_user(message.from_user.id)
    lang = user.get("language", "kk") if user else "kk"
    await message.answer(get_msg("non_text", lang))


@router.message(F.text)
async def handle_text_message(
    message: Message,
    db: Database,
    search_engine: SearchEngine,
    ai_engine: AIEngine,
    **kwargs,
):
    """Кэш → Контекст из базы → ChatGPT (с памятью) → Кэш."""
    original_text = message.text.strip()
    normalized = normalize_text(original_text)
    if not normalized:
        user = await db.get_user(message.from_user.id)
        lang = user.get("language", "kk") if user else "kk"
        await message.answer(get_msg("non_text", lang))
        return

    await _process_question(message, db, search_engine, ai_engine, original_text, **kwargs)


async def _process_question(
    message: Message,
    db: Database,
    search_engine: SearchEngine,
    ai_engine: AIEngine,
    original_text: str,
    **kwargs,
):
    """Общая обработка вопроса (из текста или suggestion-клика)."""
    user_id = message.from_user.id
    normalized = normalize_text(original_text)

    logger.info(f"Query from {user_id}: '{original_text[:80]}'")

    user = await db.get_user(user_id)
    lang = user.get("language", "kk") if user else "kk"

    thinking_msg = await message.answer("🔄 <i>Сұрағыңыз өңделуде, күте тұрыңыз...</i>")

    is_subscribed = kwargs.get("is_subscribed", False)

    conversation_history = await db.get_conversation_history(user_id)

    # 1. Проверяем кэш
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

            await db.add_conversation_message(user_id, "user", original_text)
            await db.add_conversation_message(user_id, "assistant", answer)

            response_text = answer
            if sources:
                source_label = get_msg("source_label", lang)
                response_text += f"\n\n{source_label}: {sources}"

            if not is_subscribed and WARNING_AT <= new_count < FREE_ANSWERS_LIMIT:
                remaining = FREE_ANSWERS_LIMIT - new_count
                response_text += f"\n\n⚠️ {get_msg('warning', lang, remaining=remaining, limit=FREE_ANSWERS_LIMIT)}"

            reply_markup = get_answer_keyboard(lang=lang)
            await thinking_msg.edit_text(response_text, reply_markup=reply_markup)
            logger.info(f"Cache hit for {user_id}, sim={cached['similarity']:.4f}")
            return

    # 2. Ищем контекст в базе знаний
    context_results = await search_engine.search_context(normalized, n_results=5)

    # 3. Отправляем в ChatGPT с историей
    if not ai_engine.is_available():
        await thinking_msg.edit_text(get_msg("ai_error", lang))
        return

    ai_result = await ai_engine.ask(original_text, context_results, conversation_history, lang=lang)

    if not ai_result.get("answer"):
        await db.log_query(
            user_telegram_id=user_id, query_text=original_text,
            normalized_text=normalized, similarity_score=0.0, was_answered=False,
        )
        await thinking_msg.edit_text(get_msg("not_found", lang))
        return

    answer = ai_result["answer"]
    is_off_topic = ai_result.get("is_off_topic", False)
    is_uncertain = ai_result.get("is_uncertain", False)
    suggestions = ai_result.get("suggestions", [])
    sources_list = ai_result.get("sources", [])
    source_urls = ai_result.get("source_urls", [])
    sources_str = ", ".join(sources_list) if sources_list else ""

    # 4. Кэшируем
    if not conversation_history and not is_off_topic:
        await search_engine.cache_answer(question=normalized, answer=answer, sources=sources_str)

    log_id = await db.log_query(
        user_telegram_id=user_id, query_text=original_text,
        normalized_text=normalized, matched_question="[AI generated]",
        answer_text=answer, similarity_score=1.0, was_answered=True,
    )
    new_count = await db.increment_answers_count(user_id)

    await db.add_conversation_message(user_id, "user", original_text)
    await db.add_conversation_message(user_id, "assistant", answer)

    # Формируем ответ
    response_text = answer

    if sources_str and not is_off_topic:
        source_label = get_msg("source_label", lang)
        response_text += f"\n\n{source_label}: {sources_str}"

    if source_urls and not is_off_topic:
        for url in source_urls:
            if "islam.kz" in url:
                response_text += f"\n🔗 islam.kz: {url}"
            elif "muftyat.kz" in url:
                response_text += f"\n🔗 muftyat.kz: {url}"

    if is_uncertain:
        if lang == "ru":
            response_text += (
                "\n\n⚠️ <i>Я не полностью уверен в этом ответе. "
                "Рекомендуем задать вопрос устазу для точного ответа.</i>"
            )
        else:
            response_text += (
                "\n\n⚠️ <i>Бұл жауаптың толық дұрыстығына сенімді емеспін. "
                "Нақты жауап алу үшін устазға сұрақ қоюды ұсынамыз.</i>"
            )

    if not is_subscribed and WARNING_AT <= new_count < FREE_ANSWERS_LIMIT:
        remaining = FREE_ANSWERS_LIMIT - new_count
        response_text += f"\n\n⚠️ {get_msg('warning', lang, remaining=remaining, limit=FREE_ANSWERS_LIMIT)}"

    # Клавиатура: suggestions + устаз (только если uncertain) + календарь
    reply_markup = get_answer_keyboard(
        suggestions=suggestions if not is_off_topic else None,
        query_log_id=log_id,
        lang=lang,
        is_uncertain=is_uncertain,
    )

    await thinking_msg.edit_text(response_text, reply_markup=reply_markup)
    logger.info(
        f"AI answer for {user_id}, sources={sources_list}, "
        f"off_topic={is_off_topic}, uncertain={is_uncertain}, "
        f"suggestions={len(suggestions)}"
    )
