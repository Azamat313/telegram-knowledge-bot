"""
Обработчики онбординга: /start → язык → город (кнопки) → главная.
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
from core.cities import CITIES, CITY_COORDINATES
from bot.states.onboarding import OnboardingStates
from bot.handlers.user import get_main_keyboard

router = Router()

# Популярные города для кнопок (по 2 в ряд, 12 штук + "Другой город")
POPULAR_CITIES = [
    "Алматы", "Астана", "Шымкент", "Ақтөбе",
    "Қарағанды", "Тараз", "Өскемен", "Павлодар",
    "Атырау", "Ақтау", "Қостанай", "Семей",
]


def _build_language_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора языка."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇰🇿 Қазақша", callback_data="lang:kk"),
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
        ]
    ])


def _build_popular_cities_keyboard(lang: str = "kk") -> InlineKeyboardMarkup:
    """Клавиатура с популярными городами (по 2 в ряд) + кнопка 'Другой город'."""
    rows = []
    for i in range(0, len(POPULAR_CITIES), 2):
        row = []
        for city_key in POPULAR_CITIES[i:i + 2]:
            city_data = CITIES.get(city_key, {})
            name = city_data.get(lang, city_key)
            row.append(InlineKeyboardButton(
                text=name,
                callback_data=f"pcity:{city_key}",
            ))
        rows.append(row)
    # Кнопка "Другой город"
    rows.append([InlineKeyboardButton(
        text=get_msg("onboarding_other_city", lang),
        callback_data="other_city",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _build_search_results_keyboard(cities: list[dict], lang: str = "kk") -> InlineKeyboardMarkup:
    """Inline-кнопки с результатами поиска городов (до 8 штук) + назад."""
    rows = []
    for i, city in enumerate(cities[:8]):
        name = city.get("name", "")
        rows.append([InlineKeyboardButton(
            text=name,
            callback_data=f"scity:{i}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ──────────── /start ────────────

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


# ──────────── Выбор языка → показ городов ────────────

@router.callback_query(OnboardingStates.selecting_language, F.data.startswith("lang:"))
async def on_language_selected(callback: CallbackQuery, db: Database, state: FSMContext, **kwargs):
    """Пользователь выбрал язык — показываем кнопки городов."""
    lang = callback.data.split(":")[1]
    user_id = callback.from_user.id

    await db.update_user_language(user_id, lang)
    await state.update_data(lang=lang)
    await state.set_state(OnboardingStates.selecting_from_search)

    lang_name = LANGUAGE_NAMES.get(lang, lang)

    await callback.message.edit_text(
        f"✅ {lang_name}\n\n"
        f"{get_msg('onboarding_select_city', lang)}",
        reply_markup=_build_popular_cities_keyboard(lang),
    )
    await callback.answer()


# ──────────── Выбор популярного города → финализация ────────────

@router.callback_query(
    OnboardingStates.selecting_from_search,
    F.data.startswith("pcity:"),
)
async def on_popular_city_selected(
    callback: CallbackQuery, db: Database, state: FSMContext, **kwargs
):
    """Пользователь выбрал популярный город — завершаем онбординг."""
    city_key = callback.data.split(":", 1)[1]
    data = await state.get_data()
    lang = data.get("lang", "kk")

    coords = CITY_COORDINATES.get(city_key)
    if not coords:
        await callback.answer("Ошибка, попробуйте ещё раз")
        return

    city_data = CITIES.get(city_key, {})
    city_name = city_data.get(lang, city_key)
    city_lat, city_lng = coords

    await _finalize_onboarding(callback, db, state, city_name, city_lat, city_lng, lang)


# ──────────── "Другой город" → ввод текстом ────────────

@router.callback_query(
    OnboardingStates.selecting_from_search,
    F.data == "other_city",
)
async def on_other_city(callback: CallbackQuery, state: FSMContext, **kwargs):
    """Пользователь нажал 'Другой город' — переход к текстовому поиску."""
    data = await state.get_data()
    lang = data.get("lang", "kk")

    await state.set_state(OnboardingStates.searching_city)
    await callback.message.edit_text(get_msg("onboarding_search_prompt", lang))
    await callback.answer()


# ──────────── Текстовый поиск города ────────────

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
    """Повторный поиск города (пользователь набрал текст вместо кнопки)."""
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

    search_results = [
        {"name": c["name"], "lat": float(c["lat"]), "lng": float(c["lng"])}
        for c in cities[:8]
    ]
    await state.update_data(search_results=search_results)
    await state.set_state(OnboardingStates.selecting_from_search)
    await message.answer(
        get_msg("onboarding_search_results", lang),
        reply_markup=_build_search_results_keyboard(cities, lang),
    )


# ──────────── Выбор города из результатов поиска → финализация ────────────

@router.callback_query(
    OnboardingStates.selecting_from_search,
    F.data.startswith("scity:"),
)
async def on_search_city_selected(
    callback: CallbackQuery, db: Database, state: FSMContext, **kwargs
):
    """Пользователь выбрал город из результатов поиска."""
    idx = int(callback.data.split(":")[1])
    data = await state.get_data()
    search_results = data.get("search_results", [])
    lang = data.get("lang", "kk")

    if idx >= len(search_results):
        await callback.answer("Ошибка, попробуйте ещё раз")
        return

    city = search_results[idx]
    await _finalize_onboarding(callback, db, state, city["name"], city["lat"], city["lng"], lang)


# ──────────── Финализация онбординга ────────────

async def _finalize_onboarding(
    callback: CallbackQuery, db: Database, state: FSMContext,
    city_name: str, city_lat: float, city_lng: float, lang: str,
):
    """Сохраняем город, завершаем онбординг, показываем главное меню."""
    user_id = callback.from_user.id

    await db.update_user_city_full(user_id, city_name, city_lat, city_lng)
    await db.set_user_onboarded(user_id)

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
    logger.info(f"User {user_id} onboarded: city={city_name}, lang={lang}")


# ──────────── Noop callback ────────────

@router.callback_query(F.data == "noop")
async def on_noop(callback: CallbackQuery, **kwargs):
    """Пустое нажатие."""
    await callback.answer()
