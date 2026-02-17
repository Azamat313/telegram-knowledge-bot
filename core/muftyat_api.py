"""
Асинхронный клиент API muftyat.kz для получения городов и времён намаза.
"""

import aiohttp
from loguru import logger


class MuftyatAPI:
    BASE = "https://api.muftyat.kz"
    TIMEOUT = aiohttp.ClientTimeout(total=15)

    def __init__(self):
        self._session: aiohttp.ClientSession | None = None

    async def init(self):
        """Создать HTTP-сессию."""
        self._session = aiohttp.ClientSession(timeout=self.TIMEOUT)
        logger.info("MuftyatAPI session created")

    async def close(self):
        """Закрыть HTTP-сессию."""
        if self._session:
            await self._session.close()
            logger.info("MuftyatAPI session closed")

    async def _get(self, path: str, params: dict = None) -> dict | list | None:
        """GET-запрос с retry на 5xx."""
        url = f"{self.BASE}{path}"
        for attempt in range(2):
            try:
                async with self._session.get(url, params=params) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    if resp.status >= 500 and attempt == 0:
                        logger.warning(f"MuftyatAPI 5xx ({resp.status}), retrying: {url}")
                        continue
                    logger.error(f"MuftyatAPI error {resp.status}: {url}")
                    return None
            except Exception as e:
                if attempt == 0:
                    logger.warning(f"MuftyatAPI request error, retrying: {e}")
                    continue
                logger.error(f"MuftyatAPI request failed: {e}")
                return None
        return None

    async def search_cities(self, query: str) -> list[dict]:
        """Поиск городов по названию. Возвращает [{id, name, lat, lng}]."""
        data = await self._get("/cities/", params={"search": query})
        if data and "results" in data:
            return data["results"]
        return []

    async def get_nearest_city(self, lat: float, lng: float) -> dict | None:
        """Найти ближайший город по координатам. Возвращает {id, name, lat, lng}."""
        data = await self._get("/cities/", params={"lat": str(lat), "lng": str(lng)})
        if data and "results" in data and data["results"]:
            return data["results"][0]
        return None

    async def get_prayer_times(self, year: int, lat: float, lng: float) -> list[dict]:
        """Получить времена намаза на весь год. БЕЗ trailing slash!"""
        data = await self._get(f"/prayer-times/{year}/{lat}/{lng}")
        if data and "result" in data:
            return data["result"]
        return []
