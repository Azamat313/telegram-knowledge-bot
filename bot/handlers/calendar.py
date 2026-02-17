"""
Обработчики Рамадан-календаря.
Полный календарь на 30 дней без пагинации.
Данные загружаются из API muftyat.kz и кэшируются в prayer_times_cache.
"""

from datetime import datetime, date

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from loguru import logger

from database.db import Database
from core.muftyat_api import MuftyatAPI
from core.ramadan_calendar import (
    get_ramadan_day_number, is_ramadan,
    ensure_prayer_times,
    RAMADAN_START, RAMADAN_END,
)

router = Router()

# Дни недели
DOW_KK = {0: "Дс", 1: "Сс", 2: "Ср", 3: "Бс", 4: "Жм", 5: "Сб", 6: "Жк"}
DOW_RU = {0: "Пн", 1: "Вт", 2: "Ср", 3: "Чт", 4: "Пт", 5: "Сб", 6: "Вс"}


def _format_full_calendar(
    schedule: list[dict],
    city: str,
    lang: str = "kk",
) -> str:
    """Сформировать полный красивый календарь на весь Рамадан."""
    today_day = get_ramadan_day_number()
    dow_names = DOW_KK if lang == "kk" else DOW_RU

    # === Заголовок ===
    if lang == "ru":
        lines = ["🌙 <b>РАМАДАН 2026</b>"]
        lines.append(f"📍 {city}")
    else:
        lines = ["🌙 <b>РАМАЗАН 2026</b>"]
        lines.append(f"📍 {city}")

    lines.append("")

    # === Сегодняшний день (выделенный блок) ===
    if today_day and 1 <= today_day <= len(schedule):
        today_info = schedule[today_day - 1]
        try:
            dt = datetime.strptime(today_info["date"], "%Y-%m-%d")
            dow = dow_names.get(dt.weekday(), "")
        except (ValueError, KeyError):
            dow = ""

        day_date = today_info["date"][5:]  # MM-DD
        fajr = today_info["fajr"]
        maghrib = today_info["maghrib"]

        if lang == "ru":
            lines.append(f"📌 <b>СЕГОДНЯ: {today_day}-й день</b> ({day_date}, {dow})")
            lines.append(f"    🌅 Сухур:  <b>{fajr}</b>")
            lines.append(f"    🌇 Ифтар:  <b>{maghrib}</b>")
        else:
            lines.append(f"📌 <b>БҮГІН: {today_day}-күн</b> ({day_date}, {dow})")
            lines.append(f"    🌅 Сәресі:   <b>{fajr}</b>")
            lines.append(f"    🌇 Ауызашар: <b>{maghrib}</b>")

        lines.append("")
    elif not is_ramadan():
        days_left = (RAMADAN_START - date.today()).days
        if days_left > 0:
            if lang == "ru":
                lines.append(f"⏳ До Рамадана: <b>{days_left} дн.</b>")
            else:
                lines.append(f"⏳ Рамазанға: <b>{days_left} күн</b>")
            lines.append("")

    # === Таблица ===
    lines.append("▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬")

    if lang == "ru":
        lines.append("<code> №  Дата   Дн  Сухур  Ифтар</code>")
    else:
        lines.append("<code> №  Күні   Кн  Сәрес  Ауыз.</code>")

    lines.append("▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬")

    for i, day_info in enumerate(schedule):
        day_num = i + 1
        date_str = day_info["date"][5:]  # MM-DD → "02-19"
        fajr = day_info["fajr"]
        maghrib = day_info["maghrib"]

        try:
            dt = datetime.strptime(day_info["date"], "%Y-%m-%d")
            dow = dow_names.get(dt.weekday(), "  ")
        except (ValueError, KeyError):
            dow = "  "

        # Маркер текущего дня
        if today_day and day_num == today_day:
            marker = " ◀"
        else:
            marker = ""

        line = f"{day_num:>2}  {date_str}  {dow}  {fajr}  {maghrib}{marker}"
        lines.append(f"<code>{line}</code>")

        # Визуальный разделитель каждые 10 дней
        if day_num % 10 == 0 and day_num < len(schedule):
            lines.append("<code>  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─</code>")

    lines.append("▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬")

    # Подпись
    if lang == "ru":
        lines.append("🌅 Сухур — прекратить еду  |  🌇 Ифтар — разговение")
    else:
        lines.append("🌅 Сәресі — тамақ тоқтату  |  🌇 Ауызашар")

    return "\n".join(lines)


async def _get_ramadan_schedule(
    db: Database, muftyat_api: MuftyatAPI, city: str, lat: float, lng: float
) -> list[dict]:
    """Получить расписание Рамадана из кэша или API."""
    await ensure_prayer_times(muftyat_api, db, city, lat, lng)

    all_days = await db.get_cached_prayer_times(
        lat, lng,
        RAMADAN_START.isoformat(),
        RAMADAN_END.isoformat(),
    )
    return all_days


async def _show_calendar(target, db: Database, muftyat_api: MuftyatAPI, user_id: int, edit: bool = False):
    """Показать полный календарь."""
    user = await db.get_user(user_id)
    lang = user.get("language", "kk") if user else "kk"
    city = user.get("city") if user else None
    lat = user.get("city_lat") if user else None
    lng = user.get("city_lng") if user else None

    if not city or lat is None or lng is None:
        if lang == "ru":
            text = "📍 Сначала выберите город: /start"
        else:
            text = "📍 Алдымен қалаңызды таңдаңыз: /start"
        if edit and hasattr(target, "edit_text"):
            await target.edit_text(text)
        else:
            await target.answer(text)
        return

    schedule = await _get_ramadan_schedule(db, muftyat_api, city, lat, lng)
    if not schedule:
        if lang == "ru":
            text = "Рамадан ещё не начался или уже закончился."
        else:
            text = "Рамазан әлі басталмаған немесе аяқталған."
        if edit and hasattr(target, "edit_text"):
            await target.edit_text(text)
        else:
            await target.answer(text)
        return

    text = _format_full_calendar(schedule, city, lang)

    if edit and hasattr(target, "edit_text"):
        await target.edit_text(text)
    else:
        await target.answer(text)


# Казахский текст кнопки
@router.message(F.text == "📅 Күнтізбе")
async def btn_calendar_kk(message: Message, db: Database, muftyat_api: MuftyatAPI, **kwargs):
    await _show_calendar(message, db, muftyat_api, message.from_user.id)


# Русский текст кнопки
@router.message(F.text == "📅 Календарь")
async def btn_calendar_ru(message: Message, db: Database, muftyat_api: MuftyatAPI, **kwargs):
    await _show_calendar(message, db, muftyat_api, message.from_user.id)


# Inline-кнопка календаря под ответом ИИ
@router.callback_query(F.data == "show_calendar")
async def on_show_calendar(callback: CallbackQuery, db: Database, muftyat_api: MuftyatAPI, **kwargs):
    """Кнопка календаря под ответом."""
    await _show_calendar(callback.message, db, muftyat_api, callback.from_user.id)
    await callback.answer()
