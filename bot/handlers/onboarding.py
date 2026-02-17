"""
Обработчики онбординга: /start → геолокация/поиск города → язык → главная.
"""

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from loguru import logger

from database.db import Database
from core.messages import get_msg, LANGUAGE_NAMES
from core.muftyat_api import MuftyatAPI
from bot.states.onboarding import OnboardingStates
from bot.handlers.user import get_main_keyboard

router = Router()


def _build_location_keyboard() -> ReplyKeyboardMarkup:
    """ReplyKeyboard с кнопкой геолокации и ручного ввода."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(
                text="📍 Орналасқанымды жіберу / Отправить геолокацию",
                request_location=True,
            )],
            [KeyboardButton(text="🔍 Қалаңызды қолмен теріңіз / Ввести город вручную")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _build_confirm_keyboard() -> InlineKeyboardMarkup:
    """Inline-клавиатура подтверждения города."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Иә ✅ / Да ✅", callback_data="confirm_city:yes"),
            InlineKeyboardButton(text="Басқа қала 🔄 / Другой город", callback_data="confirm_city:no"),
        ]
    ])


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
        await state.set_state(OnboardingStates.waiting_location)
        await message.answer(
            get_msg("onboarding_welcome", "kk"),
            reply_markup=ReplyKeyboardRemove(),
        )
        await message.answer(
            "📍 Геолокацияңызды жіберіңіз немесе қалаңызды қолмен теріңіз:\n"
            "📍 Отправьте геолокацию или введите название города вручную:",
            reply_markup=_build_location_keyboard(),
        )
    else:
        lang = user.get("language", "kk")
        first_name = message.from_user.first_name or ""
        await message.answer(
            get_msg("welcome_back", lang, first_name=first_name),
            reply_markup=get_main_keyboard(lang),
        )


# ──────────── Вариант A: Геолокация ────────────

@router.message(OnboardingStates.waiting_location, F.location)
async def on_location_received(
    message: Message, db: Database, state: FSMContext, muftyat_api: MuftyatAPI, **kwargs
):
    """Пользователь отправил геолокацию."""
    lat = message.location.latitude
    lng = message.location.longitude

    city = await muftyat_api.get_nearest_city(lat, lng)
    if not city:
        await message.answer(
            "Қызмет уақытша қол жетімсіз. Қалаңызды қолмен жазыңыз:\n"
            "Сервис временно недоступен. Введите город вручную:",
            reply_markup=ReplyKeyboardRemove(),
        )
        await state.set_state(OnboardingStates.selecting_from_search)
        return

    city_name = city["name"]
    city_lat = float(city["lat"])
    city_lng = float(city["lng"])

    await state.update_data(city_name=city_name, city_lat=city_lat, city_lng=city_lng)
    await state.set_state(OnboardingStates.confirming_city)

    await message.answer(
        f"📍 Сіздің қалаңыз / Ваш город: <b>{city_name}</b>\nДұрыс па? / Всё верно?",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer(
        "Таңдаңыз / Выберите:",
        reply_markup=_build_confirm_keyboard(),
    )


# ──────────── Подтверждение города ────────────

@router.callback_query(OnboardingStates.confirming_city, F.data == "confirm_city:yes")
async def on_city_confirmed(callback: CallbackQuery, db: Database, state: FSMContext, **kwargs):
    """Пользователь подтвердил город — переходим к выбору языка."""
    data = await state.get_data()
    city_name = data["city_name"]
    city_lat = data["city_lat"]
    city_lng = data["city_lng"]

    await db.update_user_city_full(callback.from_user.id, city_name, city_lat, city_lng)
    await state.set_state(OnboardingStates.selecting_language)

    await callback.message.edit_text(
        f"✅ {city_name}\n\n🌐 Тілді таңдаңыз / Выберите язык:",
        reply_markup=_build_language_keyboard(),
    )
    await callback.answer()


@router.callback_query(OnboardingStates.confirming_city, F.data == "confirm_city:no")
async def on_city_rejected(callback: CallbackQuery, state: FSMContext, **kwargs):
    """Пользователь хочет другой город — переходим к текстовому поиску."""
    await state.set_state(OnboardingStates.selecting_from_search)
    await callback.message.edit_text(
        "Қалаңызды жазыңыз / Введите название города:"
    )
    await callback.answer()


# ──────────── Вариант B: Ручной ввод / кнопка "Вручную" ────────────

@router.message(
    OnboardingStates.waiting_location,
    F.text == "🔍 Қалаңызды қолмен теріңіз / Ввести город вручную",
)
async def on_manual_input_button(message: Message, state: FSMContext, **kwargs):
    """Кнопка ручного ввода города."""
    await state.set_state(OnboardingStates.selecting_from_search)
    await message.answer(
        "Қалаңызды жазыңыз / Введите название города:",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(OnboardingStates.waiting_location, F.text)
async def on_text_during_location(
    message: Message, state: FSMContext, muftyat_api: MuftyatAPI, **kwargs
):
    """Пользователь ввёл текст вместо геолокации — пробуем поиск."""
    await _do_city_search(message, state, muftyat_api, message.text)


@router.message(OnboardingStates.selecting_from_search, F.text)
async def on_city_search_text(
    message: Message, state: FSMContext, muftyat_api: MuftyatAPI, **kwargs
):
    """Текстовый поиск города."""
    await _do_city_search(message, state, muftyat_api, message.text)


async def _do_city_search(
    message: Message, state: FSMContext, api: MuftyatAPI, query: str
):
    """Общий поиск города через API."""
    cities = await api.search_cities(query.strip())
    if not cities:
        await message.answer(
            "Ештеңе табылмады. Қайта жазып көріңіз:\n"
            "Ничего не найдено. Попробуйте ещё раз:"
        )
        await state.set_state(OnboardingStates.selecting_from_search)
        return

    if len(cities) == 1:
        # Единственный результат — сразу подтверждение
        city = cities[0]
        city_name = city["name"]
        city_lat = float(city["lat"])
        city_lng = float(city["lng"])
        await state.update_data(city_name=city_name, city_lat=city_lat, city_lng=city_lng)
        await state.set_state(OnboardingStates.confirming_city)
        await message.answer(
            f"📍 Сіздің қалаңыз / Ваш город: <b>{city_name}</b>\nДұрыс па? / Всё верно?",
            reply_markup=_build_confirm_keyboard(),
        )
    else:
        # Несколько результатов — сохраняем в FSM и показываем inline-кнопки
        search_results = [
            {"name": c["name"], "lat": float(c["lat"]), "lng": float(c["lng"])}
            for c in cities[:8]
        ]
        await state.update_data(search_results=search_results)
        await state.set_state(OnboardingStates.selecting_from_search)
        await message.answer(
            "Қалаңызды таңдаңыз / Выберите ваш город:",
            reply_markup=_build_search_results_keyboard(cities),
        )


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

    if idx >= len(search_results):
        await callback.answer("Ошибка, попробуйте ещё раз")
        return

    city = search_results[idx]
    city_name = city["name"]
    city_lat = city["lat"]
    city_lng = city["lng"]

    await db.update_user_city_full(callback.from_user.id, city_name, city_lat, city_lng)
    await state.update_data(city_name=city_name, city_lat=city_lat, city_lng=city_lng)
    await state.set_state(OnboardingStates.selecting_language)

    await callback.message.edit_text(
        f"✅ {city_name}\n\n🌐 Тілді таңдаңыз / Выберите язык:",
        reply_markup=_build_language_keyboard(),
    )
    await callback.answer()


# ──────────── Выбор языка ────────────

@router.callback_query(OnboardingStates.selecting_language, F.data.startswith("lang:"))
async def on_language_selected(callback: CallbackQuery, db: Database, state: FSMContext, **kwargs):
    """Пользователь выбрал язык — завершаем онбординг."""
    lang = callback.data.split(":")[1]
    user_id = callback.from_user.id

    await db.update_user_language(user_id, lang)
    await db.set_user_onboarded(user_id)

    data = await state.get_data()
    city_name = data.get("city_name", "")
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
