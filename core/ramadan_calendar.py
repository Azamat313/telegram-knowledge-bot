"""
Логика Рамадан-календаря: загрузка данных из API muftyat.kz, кэширование, фильтрация.
"""

from datetime import date

from loguru import logger


RAMADAN_START = date(2026, 2, 19)
RAMADAN_END = date(2026, 3, 20)  # 30 дней


def get_ramadan_day_number() -> int | None:
    """Получить номер текущего дня Рамадана (1-30) или None если не Рамадан."""
    today = date.today()
    if today < RAMADAN_START or today > RAMADAN_END:
        return None
    return (today - RAMADAN_START).days + 1


def is_ramadan() -> bool:
    """Проверить, идёт ли Рамадан сейчас."""
    return get_ramadan_day_number() is not None


async def ensure_prayer_times(api, db, city_name: str, lat: float, lng: float):
    """Загрузить и закэшировать данные если нет в кэше."""
    if await db.is_prayer_times_cached(lat, lng, 2026):
        return True
    try:
        data = await api.get_prayer_times(2026, lat, lng)
        if not data:
            logger.warning(f"No prayer times from API for {city_name} ({lat}, {lng})")
            return False
        await db.cache_prayer_times(city_name, lat, lng, data)
        logger.info(f"Prayer times cached: {city_name} ({lat}, {lng}), {len(data)} days")
        return True
    except Exception as e:
        logger.error(f"Failed to load prayer times for {city_name}: {e}")
        return False


def filter_ramadan_days(all_days: list[dict]) -> list[dict]:
    """Из кэшированных записей отфильтровать дни Рамадана (19.02-20.03.2026)."""
    start_str = RAMADAN_START.isoformat()
    end_str = RAMADAN_END.isoformat()
    ramadan_days = []
    for day in all_days:
        d = day.get("date", "")
        if start_str <= d <= end_str:
            ramadan_days.append(day)
    return ramadan_days
