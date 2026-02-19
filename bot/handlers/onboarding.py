"""
Обработчики онбординга: /start → язык → поиск города → выбор из списка → главная.
"""

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from loguru import logger

from database.db import Database
from core.messages import get_msg, LANGUAGE_NAMES
from core.muftyat_api import MuftyatAPI
from bot.states.onboarding import OnboardingStates
from bot.handlers.user import get_main_keyboard

router = Router()


def _build_search_results_keyboard(cities: list[dict]) -> InlineKeyboardMarkup:
    """Inline-кнопки с результатами поиска городов (до 8 штук)."""
    rows = []
    for i, city in enumerate(cities[:8]):
        name = city.get("name", "")
        rows.append([InlineKeyboardButton(
            text=name,
            callback_data=f"scity:{i}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _build_language_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора языка."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇰🇿 Қазақша", callback_data="lang:kk"),
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
        ]
    ])


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database, state: FSMContext, **kwargs):
    """Обработка /start — онбординг или приветствие."""
    user = await db.get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )

    if not user.get("is_onboarded"):
        await state.set_state(OnboardingStates.selecting_language)
        await message.answer(
            "Ассалаумағалейкум! 🌙\n"
            "Ассаляму алейкум! 🌙\n\n"
            "🌐 Тілді таңдаңыз / Выберите язык:",
            reply_markup=_build_language_keyboard(),
        )
    else:
        lang = user.get("language", "kk")
        first_name = message.from_user.first_name or ""
        await message.answer(
            get_msg("welcome_back", lang, first_name=first_name),
            reply_markup=get_main_keyboard(lang),
        )


# ──────────── Выбор языка ────────────

@router.callback_query(OnboardingStates.selecting_language, F.data.startswith("lang:"))
async def on_language_selected(callback: CallbackQuery, db: Database, state: FSMContext, **kwargs):
    """Пользователь выбрал язык — сохраняем и спрашиваем город."""
    lang = callback.data.split(":")[1]
    user_id = callback.from_user.id

    await db.update_user_language(user_id, lang)
    await state.update_data(lang=lang)
    await state.set_state(OnboardingStates.searching_city)

    lang_name = LANGUAGE_NAMES.get(lang, lang)

    await callback.message.edit_text(
        f"✅ {lang_name}\n\n"
        f"{get_msg('onboarding_search_prompt', lang)}"
    )
    await callback.answer()


# ──────────── Поиск города ────────────

@router.message(OnboardingStates.searching_city, F.text)
async def on_city_search(
    message: Message, state: FSMContext, muftyat_api: MuftyatAPI, **kwargs
):
    """Пользователь ввёл название города — ищем через API."""
    await _do_city_search(message, state, muftyat_api, message.text)


@router.message(OnboardingStates.selecting_from_search, F.text)
async def on_city_search_retry(
    message: Message, state: FSMContext, muftyat_api: MuftyatAPI, **kwargs
):
    """Повторный поиск города."""
    await _do_city_search(message, state, muftyat_api, message.text)


async def _do_city_search(
    message: Message, state: FSMContext, api: MuftyatAPI, query: str
):
    """Поиск города через API muftyat.kz."""
    data = await state.get_data()
    lang = data.get("lang", "kk")

    cities = await api.search_cities(query.strip())
    if not cities:
        await message.answer(get_msg("onboarding_search_no_results", lang))
        await state.set_state(OnboardingStates.searching_city)
        return

    # Сохраняем результаты в FSM и показываем inline-кнопки
    search_results = [
        {"name": c["name"], "lat": float(c["lat"]), "lng": float(c["lng"])}
        for c in cities[:8]
    ]
    await state.update_data(search_results=search_results)
    await state.set_state(OnboardingStates.selecting_from_search)
    await message.answer(
        get_msg("onboarding_search_results", lang),
        reply_markup=_build_search_results_keyboard(cities),
    )


# ──────────── Выбор города из списка → финализация ────────────

@router.callback_query(
    OnboardingStates.selecting_from_search,
    F.data.startswith("scity:"),
)
async def on_search_city_selected(
    callback: CallbackQuery, db: Database, state: FSMContext, **kwargs
):
    """Пользователь выбрал город — завершаем онбординг."""
    idx = int(callback.data.split(":")[1])
    data = await state.get_data()
    search_results = data.get("search_results", [])
    lang = data.get("lang", "kk")

    if idx >= len(search_results):
        await callback.answer("Ошибка, попробуйте ещё раз")
        return

    city = search_results[idx]
    city_name = city["name"]
    city_lat = city["lat"]
    city_lng = city["lng"]

    await db.update_user_city_full(callback.from_user.id, city_name, city_lat, city_lng)
    await db.set_user_onboarded(callback.from_user.id)

    lang_name = LANGUAGE_NAMES.get(lang, lang)

    await state.clear()

    await callback.message.edit_text(
        get_msg("onboarding_complete", lang, city=city_name, language=lang_name),
    )

    await callback.message.answer(
        get_msg("welcome", lang),
        reply_markup=get_main_keyboard(lang),
    )
    await callback.answer()
    logger.info(f"User {callback.from_user.id} onboarded: city={city_name}, lang={lang}")


# ──────────── Noop callback ────────────

@router.callback_query(F.data == "noop")
async def on_noop(callback: CallbackQuery, **kwargs):
    """Пустое нажатие."""
    await callback.answer()
