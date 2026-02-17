"""
Обработчики Рамадан-календаря.
Отображение расписания по неделям с пагинацией.
Данные загружаются из API muftyat.kz и кэшируются в prayer_times_cache.
"""

from datetime import datetime

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from loguru import logger

from database.db import Database
from core.messages import get_msg
from core.muftyat_api import MuftyatAPI
from core.ramadan_calendar import (
    get_ramadan_day_number, is_ramadan,
    ensure_prayer_times, filter_ramadan_days,
    RAMADAN_START, RAMADAN_END,
)

router = Router()


def _build_week_buttons(lang: str = "kk", current_week: int = 1) -> InlineKeyboardMarkup:
    """Кнопки пагинации по неделям."""
    buttons = []
    for w in range(1, 6):  # 5 недель максимум (30 дней)
        label = get_msg("calendar_week", lang, n=w)
        if w == current_week:
            label = f"• {label} •"
        buttons.append(InlineKeyboardButton(
            text=label,
            callback_data=f"cal_week:{w}",
        ))
    # Разбиваем на 2 ряда
    return InlineKeyboardMarkup(inline_keyboard=[
        buttons[:3],
        buttons[3:],
    ])


def _format_calendar_week(
    schedule: list[dict],
    week: int,
    city: str,
    lang: str = "kk",
) -> str:
    """Сформировать текст календаря на одну неделю."""
    today_day = get_ramadan_day_number()

    # Заголовок
    title = get_msg("calendar_title", lang, city=city)
    sahoor_label = get_msg("calendar_sahoor", lang)
    iftar_label = get_msg("calendar_iftar", lang)

    lines = [f"<b>{title}</b>\n"]

    # Сегодняшний день
    if today_day and 1 <= today_day <= len(schedule):
        today_info = schedule[today_day - 1]
        try:
            dow = datetime.strptime(today_info["date"], "%Y-%m-%d").strftime("%A")
        except (ValueError, KeyError):
            dow = ""
        lines.append(
            get_msg("calendar_today", lang,
                    day=today_day, date=today_info["date"],
                    dow=dow)
        )
        lines.append(
            f"{sahoor_label}: <b>{today_info['fajr']}</b>  |  "
            f"{iftar_label}: <b>{today_info['maghrib']}</b>"
        )
        lines.append("")

    # Таблица недели
    start = (week - 1) * 7
    end = min(start + 7, len(schedule))
    week_days = schedule[start:end]

    if not week_days:
        return "\n".join(lines) + "\n(Бұл аптада күн жоқ)"

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    header = get_msg("calendar_header", lang)
    lines.append(f"<code>{header}</code>")

    for i, day_info in enumerate(week_days):
        day_num = start + i + 1
        date_str = day_info["date"]
        fajr = day_info["fajr"]
        maghrib = day_info["maghrib"]

        # Маркер текущего дня
        marker = " 👈" if today_day and day_num == today_day else ""

        line = f"{day_num:>2}  {date_str}  {fajr:>5}   {maghrib:>5}{marker}"
        lines.append(f"<code>{line}</code>")

    lines.append("━━━━━━━━━━━━━━━━━━━━")

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


async def _show_calendar(
    target, db: Database, muftyat_api: MuftyatAPI,
    user_id: int, week: int = 1, edit: bool = False,
):
    """Показать календарь (для message и callback)."""
    user = await db.get_user(user_id)
    lang = user.get("language", "kk") if user else "kk"
    city = user.get("city") if user else None
    lat = user.get("city_lat") if user else None
    lng = user.get("city_lng") if user else None

    if not city or lat is None or lng is None:
        text = get_msg("calendar_no_city", lang)
        if edit and hasattr(target, "edit_text"):
            await target.edit_text(text)
        else:
            await target.answer(text)
        return

    schedule = await _get_ramadan_schedule(db, muftyat_api, city, lat, lng)
    if not schedule:
        text = get_msg("calendar_not_ramadan", lang)
        if edit and hasattr(target, "edit_text"):
            await target.edit_text(text)
        else:
            await target.answer(text)
        return

    # Определяем текущую неделю
    today_day = get_ramadan_day_number()
    if week == 0 and today_day:
        week = (today_day - 1) // 7 + 1
    elif week == 0:
        week = 1

    text = _format_calendar_week(schedule, week, city, lang)
    keyboard = _build_week_buttons(lang, week)

    if edit and hasattr(target, "edit_text"):
        await target.edit_text(text, reply_markup=keyboard)
    else:
        await target.answer(text, reply_markup=keyboard)


# Казахский текст кнопки
@router.message(F.text == "📅 Күнтізбе")
async def btn_calendar_kk(message: Message, db: Database, muftyat_api: MuftyatAPI, **kwargs):
    await _show_calendar(message, db, muftyat_api, message.from_user.id, week=0)


# Русский текст кнопки
@router.message(F.text == "📅 Календарь")
async def btn_calendar_ru(message: Message, db: Database, muftyat_api: MuftyatAPI, **kwargs):
    await _show_calendar(message, db, muftyat_api, message.from_user.id, week=0)


# Inline-кнопка календаря под ответом ИИ
@router.callback_query(F.data == "show_calendar")
async def on_show_calendar(callback: CallbackQuery, db: Database, muftyat_api: MuftyatAPI, **kwargs):
    """Кнопка календаря под ответом."""
    await _show_calendar(callback.message, db, muftyat_api, callback.from_user.id, week=0)
    await callback.answer()


@router.callback_query(F.data.startswith("cal_week:"))
async def on_calendar_week(callback: CallbackQuery, db: Database, muftyat_api: MuftyatAPI, **kwargs):
    """Переключение недели в календаре."""
    week = int(callback.data.split(":")[1])
    await _show_calendar(
        callback.message, db, muftyat_api,
        callback.from_user.id, week=week, edit=True,
    )
    await callback.answer()
