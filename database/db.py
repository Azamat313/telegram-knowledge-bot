"""
Асинхронная работа с SQLite через aiosqlite.
Управление пользователями, логами запросов, подписками,
историей диалогов, устаз-консультациями, расписанием Рамадана,
модераторскими тикетами.
"""

import os
from datetime import datetime, timedelta
from typing import Optional

import aiosqlite
from loguru import logger

from config import DATABASE_PATH, CONVERSATION_HISTORY_LIMIT, USTAZ_MONTHLY_LIMIT
from database.models import CREATE_TABLES_SQL


class Database:
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self):
        """Подключение к БД и создание таблиц."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row

        # Оптимизация для параллельного доступа
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.execute("PRAGMA cache_size=-8000")

        await self._conn.executescript(CREATE_TABLES_SQL)
        await self._conn.commit()

        # Миграции для существующих БД
        await self._run_migrations()

        logger.info(f"Database connected: {self.db_path} (WAL mode)")

    async def _run_migrations(self):
        """Запуск миграций для добавления новых колонок."""
        migrations = [
            ("subscriptions", "telegram_payment_charge_id", "TEXT"),
            ("users", "city", "TEXT DEFAULT NULL"),
            ("users", "language", "TEXT DEFAULT 'kk'"),
            ("users", "is_onboarded", "BOOLEAN DEFAULT FALSE"),
            ("users", "city_lat", "REAL DEFAULT NULL"),
            ("users", "city_lng", "REAL DEFAULT NULL"),
        ]
        for table, column, col_type in migrations:
            try:
                await self._conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
                )
                await self._conn.commit()
                logger.info(f"Migration: added {table}.{column}")
            except Exception:
                pass  # Колонка уже существует

        # Миграция существующих пользователей: city → city_lat/city_lng
        await self._migrate_city_coordinates()

    async def close(self):
        """Закрытие соединения."""
        if self._conn:
            await self._conn.close()
            logger.info("Database connection closed")

    # ──────────────────────── Users ────────────────────────

    async def get_or_create_user(
        self, telegram_id: int, username: str = None, first_name: str = None
    ) -> dict:
        """Получить или создать пользователя."""
        cursor = await self._conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cursor.fetchone()

        if row:
            user = dict(row)
            # Обновляем username/first_name если изменились
            if username != user.get("username") or first_name != user.get("first_name"):
                await self._conn.execute(
                    "UPDATE users SET username = ?, first_name = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE telegram_id = ?",
                    (username, first_name, telegram_id),
                )
                await self._conn.commit()
            return user

        await self._conn.execute(
            "INSERT INTO users (telegram_id, username, first_name) VALUES (?, ?, ?)",
            (telegram_id, username, first_name),
        )
        await self._conn.commit()
        logger.info(f"New user created: {telegram_id} ({username})")

        cursor = await self._conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        return dict(await cursor.fetchone())

    async def get_user(self, telegram_id: int) -> Optional[dict]:
        """Получить пользователя по telegram_id."""
        cursor = await self._conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def increment_answers_count(self, telegram_id: int) -> int:
        """Увеличить счётчик ответов на 1. Возвращает новое значение."""
        await self._conn.execute(
            "UPDATE users SET answers_count = answers_count + 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE telegram_id = ?",
            (telegram_id,),
        )
        await self._conn.commit()
        cursor = await self._conn.execute(
            "SELECT answers_count FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cursor.fetchone()
        return row["answers_count"]

    async def check_subscription(self, telegram_id: int) -> bool:
        """Проверить, активна ли подписка (по флагу + дате)."""
        user = await self.get_user(telegram_id)
        if not user:
            return False

        if not user["is_subscribed"]:
            return False

        expires = user.get("subscription_expires_at")
        if expires:
            expires_dt = datetime.fromisoformat(expires)
            if expires_dt < datetime.now():
                # Подписка истекла
                await self._conn.execute(
                    "UPDATE users SET is_subscribed = FALSE, subscription_expires_at = NULL, "
                    "updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
                    (telegram_id,),
                )
                await self._conn.commit()
                return False

        return True

    # ──────────────────── User City/Language/Onboarding ────────────────────

    async def update_user_city(self, telegram_id: int, city: str):
        """Обновить город пользователя."""
        await self._conn.execute(
            "UPDATE users SET city = ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
            (city, telegram_id),
        )
        await self._conn.commit()

    async def update_user_language(self, telegram_id: int, language: str):
        """Обновить язык пользователя."""
        await self._conn.execute(
            "UPDATE users SET language = ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
            (language, telegram_id),
        )
        await self._conn.commit()

    async def set_user_onboarded(self, telegram_id: int):
        """Пометить пользователя как прошедшего онбординг."""
        await self._conn.execute(
            "UPDATE users SET is_onboarded = TRUE, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
            (telegram_id,),
        )
        await self._conn.commit()

    async def update_user_city_full(
        self, telegram_id: int, city_name: str, lat: float, lng: float
    ):
        """Сохранить город + координаты пользователя."""
        await self._conn.execute(
            "UPDATE users SET city = ?, city_lat = ?, city_lng = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
            (city_name, lat, lng, telegram_id),
        )
        await self._conn.commit()

    async def _migrate_city_coordinates(self):
        """Миграция существующих пользователей: заполнить city_lat/city_lng из CITY_COORDINATES."""
        from core.cities import CITY_COORDINATES

        cursor = await self._conn.execute(
            "SELECT telegram_id, city FROM users WHERE city IS NOT NULL AND city_lat IS NULL"
        )
        rows = await cursor.fetchall()
        migrated = 0
        for row in rows:
            coords = CITY_COORDINATES.get(row["city"])
            if coords:
                await self._conn.execute(
                    "UPDATE users SET city_lat = ?, city_lng = ? WHERE telegram_id = ?",
                    (coords[0], coords[1], row["telegram_id"]),
                )
                migrated += 1
        if migrated:
            await self._conn.commit()
            logger.info(f"Migrated {migrated} users with city coordinates")

    # ──────────────── Users grouped by coordinates ──────────────

    async def get_users_grouped_by_coordinates(self) -> list[dict]:
        """DISTINCT (city_lat, city_lng, city) для onboarded юзеров."""
        cursor = await self._conn.execute(
            "SELECT DISTINCT city_lat, city_lng, city FROM users "
            "WHERE is_onboarded = TRUE AND city_lat IS NOT NULL AND city_lng IS NOT NULL"
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_users_by_coordinates(self, lat: float, lng: float) -> list[dict]:
        """Все onboarded юзеры с данными координатами."""
        cursor = await self._conn.execute(
            "SELECT telegram_id, language, first_name FROM users "
            "WHERE is_onboarded = TRUE AND city_lat = ? AND city_lng = ?",
            (lat, lng),
        )
        return [dict(row) for row in await cursor.fetchall()]

    # ──────────────────── Prayer Times Cache ────────────────────

    async def cache_prayer_times(
        self, city_name: str, lat: float, lng: float, prayer_list: list[dict]
    ):
        """Массовый INSERT времён намаза из API-ответа."""
        for item in prayer_list:
            await self._conn.execute(
                "INSERT OR REPLACE INTO prayer_times_cache "
                "(city_name, lat, lng, date, imsak, fajr, sunrise, dhuhr, asr, maghrib, isha) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    city_name, lat, lng,
                    item.get("Date", ""),
                    item.get("imsak", ""),
                    item.get("fajr", ""),
                    item.get("sunrise", ""),
                    item.get("dhuhr", ""),
                    item.get("asr", ""),
                    item.get("maghrib", ""),
                    item.get("isha", ""),
                ),
            )
        await self._conn.commit()
        logger.info(f"Cached {len(prayer_list)} prayer times for {city_name} ({lat}, {lng})")

    async def get_cached_prayer_times(
        self, lat: float, lng: float, date_from: str, date_to: str
    ) -> list[dict]:
        """Получить кэшированные времена намаза за период."""
        cursor = await self._conn.execute(
            "SELECT * FROM prayer_times_cache "
            "WHERE lat = ? AND lng = ? AND date >= ? AND date <= ? "
            "ORDER BY date",
            (lat, lng, date_from, date_to),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def is_prayer_times_cached(self, lat: float, lng: float, year: int) -> bool:
        """Проверить наличие кэшированных данных за год."""
        cursor = await self._conn.execute(
            "SELECT COUNT(*) as cnt FROM prayer_times_cache "
            "WHERE lat = ? AND lng = ? AND date LIKE ?",
            (lat, lng, f"{year}-%"),
        )
        row = await cursor.fetchone()
        return row["cnt"] > 0

    # ──────────────────────── Subscriptions ────────────────────────

    async def grant_subscription(
        self,
        telegram_id: int,
        plan_name: str = "manual",
        days: int = 30,
        amount: float = 0,
        currency: str = "XTR",
        payment_method: str = None,
        payment_id: str = None,
    ):
        """Выдать подписку пользователю."""
        expires_at = datetime.now() + timedelta(days=days)

        await self._conn.execute(
            "UPDATE users SET is_subscribed = TRUE, subscription_expires_at = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
            (expires_at.isoformat(), telegram_id),
        )

        await self._conn.execute(
            "INSERT INTO subscriptions "
            "(user_telegram_id, plan_name, amount, currency, expires_at, "
            "payment_method, payment_id, telegram_payment_charge_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (telegram_id, plan_name, amount, currency, expires_at.isoformat(),
             payment_method, payment_id, payment_id),
        )
        await self._conn.commit()
        logger.info(f"Subscription granted: user={telegram_id}, plan={plan_name}, days={days}")

    async def revoke_subscription(self, telegram_id: int):
        """Снять подписку с пользователя."""
        await self._conn.execute(
            "UPDATE users SET is_subscribed = FALSE, subscription_expires_at = NULL, "
            "updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
            (telegram_id,),
        )
        await self._conn.commit()
        logger.info(f"Subscription revoked: user={telegram_id}")

    # ──────────────────────── Query Logs ────────────────────────

    async def log_query(
        self,
        user_telegram_id: int,
        query_text: str,
        normalized_text: str,
        matched_question: str = None,
        answer_text: str = None,
        similarity_score: float = None,
        was_answered: bool = False,
    ) -> int:
        """Записать лог запроса. Возвращает ID записи."""
        cursor = await self._conn.execute(
            "INSERT INTO query_logs "
            "(user_telegram_id, query_text, normalized_text, matched_question, "
            "answer_text, similarity_score, was_answered) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                user_telegram_id,
                query_text,
                normalized_text,
                matched_question,
                answer_text,
                similarity_score,
                was_answered,
            ),
        )
        await self._conn.commit()
        return cursor.lastrowid

    # ──────────────────────── Statistics ────────────────────────

    async def get_total_users(self) -> int:
        cursor = await self._conn.execute("SELECT COUNT(*) as cnt FROM users")
        row = await cursor.fetchone()
        return row["cnt"]

    async def get_total_queries(self) -> int:
        cursor = await self._conn.execute("SELECT COUNT(*) as cnt FROM query_logs")
        row = await cursor.fetchone()
        return row["cnt"]

    async def get_answered_queries(self) -> int:
        cursor = await self._conn.execute(
            "SELECT COUNT(*) as cnt FROM query_logs WHERE was_answered = TRUE"
        )
        row = await cursor.fetchone()
        return row["cnt"]

    async def get_subscribed_users(self) -> int:
        cursor = await self._conn.execute(
            "SELECT COUNT(*) as cnt FROM users WHERE is_subscribed = TRUE"
        )
        row = await cursor.fetchone()
        return row["cnt"]

    async def get_top_unanswered(self, limit: int = 10) -> list:
        """Топ неотвеченных вопросов (для пополнения базы)."""
        cursor = await self._conn.execute(
            "SELECT query_text, COUNT(*) as cnt FROM query_logs "
            "WHERE was_answered = FALSE "
            "GROUP BY normalized_text ORDER BY cnt DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_top_questions(self, limit: int = 10) -> list:
        """Топ популярных вопросов."""
        cursor = await self._conn.execute(
            "SELECT matched_question, COUNT(*) as cnt FROM query_logs "
            "WHERE was_answered = TRUE AND matched_question IS NOT NULL "
            "GROUP BY matched_question ORDER BY cnt DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    # ──────────────────────── Conversation History ────────────────────────

    async def add_conversation_message(
        self, user_telegram_id: int, role: str, message_text: str
    ):
        """Добавить сообщение в историю диалога. role: 'user' или 'assistant'."""
        await self._conn.execute(
            "INSERT INTO conversation_history (user_telegram_id, role, message_text) "
            "VALUES (?, ?, ?)",
            (user_telegram_id, role, message_text),
        )
        await self._conn.commit()
        # Тримим историю до лимита
        await self._trim_conversation_history(user_telegram_id)

    async def get_conversation_history(
        self, user_telegram_id: int, limit: int = None
    ) -> list[dict]:
        """Получить историю диалога пользователя (от старых к новым)."""
        if limit is None:
            limit = CONVERSATION_HISTORY_LIMIT
        cursor = await self._conn.execute(
            "SELECT role, message_text, created_at FROM conversation_history "
            "WHERE user_telegram_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (user_telegram_id, limit),
        )
        rows = [dict(row) for row in await cursor.fetchall()]
        rows.reverse()  # от старых к новым
        return rows

    async def clear_conversation_history(self, user_telegram_id: int):
        """Очистить историю диалога пользователя."""
        await self._conn.execute(
            "DELETE FROM conversation_history WHERE user_telegram_id = ?",
            (user_telegram_id,),
        )
        await self._conn.commit()
        logger.info(f"Conversation history cleared for user {user_telegram_id}")

    async def _trim_conversation_history(self, user_telegram_id: int):
        """Оставить только последние N сообщений."""
        await self._conn.execute(
            "DELETE FROM conversation_history WHERE id NOT IN ("
            "  SELECT id FROM conversation_history "
            "  WHERE user_telegram_id = ? ORDER BY id DESC LIMIT ?"
            ") AND user_telegram_id = ?",
            (user_telegram_id, CONVERSATION_HISTORY_LIMIT, user_telegram_id),
        )
        await self._conn.commit()

    # ──────────────────────── Ustaz Profiles ────────────────────────

    async def add_ustaz(
        self, telegram_id: int, username: str = None, first_name: str = None
    ) -> dict:
        """Добавить устаза."""
        await self._conn.execute(
            "INSERT OR IGNORE INTO ustaz_profiles (telegram_id, username, first_name) "
            "VALUES (?, ?, ?)",
            (telegram_id, username, first_name),
        )
        await self._conn.commit()
        logger.info(f"Ustaz added: {telegram_id} ({username})")
        return await self.get_ustaz(telegram_id)

    async def get_ustaz(self, telegram_id: int) -> Optional[dict]:
        """Получить профиль устаза."""
        cursor = await self._conn.execute(
            "SELECT * FROM ustaz_profiles WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_active_ustazs(self) -> list[dict]:
        """Получить всех активных устазов."""
        cursor = await self._conn.execute(
            "SELECT * FROM ustaz_profiles WHERE is_active = TRUE"
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def remove_ustaz(self, telegram_id: int) -> bool:
        """Деактивировать устаза."""
        cursor = await self._conn.execute(
            "UPDATE ustaz_profiles SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP "
            "WHERE telegram_id = ?",
            (telegram_id,),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def update_ustaz_stats(self, telegram_id: int):
        """Увеличить счётчик ответов устаза."""
        await self._conn.execute(
            "UPDATE ustaz_profiles SET total_answered = total_answered + 1, "
            "updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
            (telegram_id,),
        )
        await self._conn.commit()

    # ──────────────────────── Consultations ────────────────────────

    async def create_consultation(
        self,
        user_telegram_id: int,
        question_text: str,
        ai_answer_text: str = None,
        conversation_context: str = None,
        query_log_id: int = None,
    ) -> int:
        """Создать заявку на консультацию. Возвращает ID."""
        cursor = await self._conn.execute(
            "INSERT INTO consultations "
            "(user_telegram_id, question_text, ai_answer_text, conversation_context, query_log_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_telegram_id, question_text, ai_answer_text, conversation_context, query_log_id),
        )
        await self._conn.commit()
        logger.info(f"Consultation created: user={user_telegram_id}, id={cursor.lastrowid}")
        return cursor.lastrowid

    async def get_consultation(self, consultation_id: int) -> Optional[dict]:
        """Получить консультацию по ID."""
        cursor = await self._conn.execute(
            "SELECT * FROM consultations WHERE id = ?", (consultation_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_pending_consultations(self, limit: int = 20) -> list[dict]:
        """Получить очередь ожидающих консультаций."""
        cursor = await self._conn.execute(
            "SELECT c.*, u.username, u.first_name FROM consultations c "
            "LEFT JOIN users u ON c.user_telegram_id = u.telegram_id "
            "WHERE c.status = 'pending' "
            "ORDER BY c.created_at ASC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def take_consultation(
        self, consultation_id: int, ustaz_telegram_id: int
    ) -> bool:
        """Устаз берёт консультацию в работу."""
        cursor = await self._conn.execute(
            "UPDATE consultations SET ustaz_telegram_id = ?, status = 'in_progress', "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND status = 'pending'",
            (ustaz_telegram_id, consultation_id),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def answer_consultation(
        self, consultation_id: int, answer_text: str
    ) -> Optional[dict]:
        """Устаз отвечает на консультацию. Возвращает обновлённую запись."""
        await self._conn.execute(
            "UPDATE consultations SET answer_text = ?, status = 'answered', "
            "answered_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (answer_text, consultation_id),
        )
        await self._conn.commit()
        return await self.get_consultation(consultation_id)

    async def get_ustaz_in_progress(self, ustaz_telegram_id: int) -> Optional[dict]:
        """Получить текущую консультацию устаза (in_progress)."""
        cursor = await self._conn.execute(
            "SELECT * FROM consultations "
            "WHERE ustaz_telegram_id = ? AND status = 'in_progress' "
            "ORDER BY updated_at DESC LIMIT 1",
            (ustaz_telegram_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_user_consultations(
        self, user_telegram_id: int, limit: int = 10
    ) -> list[dict]:
        """Получить консультации пользователя."""
        cursor = await self._conn.execute(
            "SELECT * FROM consultations "
            "WHERE user_telegram_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_telegram_id, limit),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_consultation_stats(self) -> dict:
        """Статистика консультаций."""
        stats = {}
        for status in ("pending", "in_progress", "answered"):
            cursor = await self._conn.execute(
                "SELECT COUNT(*) as cnt FROM consultations WHERE status = ?",
                (status,),
            )
            row = await cursor.fetchone()
            stats[status] = row["cnt"]
        cursor = await self._conn.execute("SELECT COUNT(*) as cnt FROM consultations")
        row = await cursor.fetchone()
        stats["total"] = row["cnt"]
        return stats

    # ──────────────────────── Ustaz Usage (Monthly Limits) ────────────────────────

    async def get_ustaz_usage(self, user_telegram_id: int) -> int:
        """Получить количество использований за текущий месяц."""
        month_year = datetime.now().strftime("%Y-%m")
        cursor = await self._conn.execute(
            "SELECT used_count FROM ustaz_usage "
            "WHERE user_telegram_id = ? AND month_year = ?",
            (user_telegram_id, month_year),
        )
        row = await cursor.fetchone()
        return row["used_count"] if row else 0

    async def increment_ustaz_usage(self, user_telegram_id: int) -> int:
        """Увеличить счётчик использований. Возвращает новое значение."""
        month_year = datetime.now().strftime("%Y-%m")
        await self._conn.execute(
            "INSERT INTO ustaz_usage (user_telegram_id, month_year, used_count) "
            "VALUES (?, ?, 1) "
            "ON CONFLICT(user_telegram_id, month_year) "
            "DO UPDATE SET used_count = used_count + 1",
            (user_telegram_id, month_year),
        )
        await self._conn.commit()
        return await self.get_ustaz_usage(user_telegram_id)

    async def check_ustaz_limit(self, user_telegram_id: int) -> tuple[bool, int]:
        """Проверить лимит обращений к устазу. Возвращает (можно_ли, осталось)."""
        used = await self.get_ustaz_usage(user_telegram_id)
        remaining = max(0, USTAZ_MONTHLY_LIMIT - used)
        return remaining > 0, remaining

    # ──────────────────────── Ramadan Schedule ────────────────────────

    async def upsert_ramadan_schedule(
        self,
        city: str,
        day_number: int,
        gregorian_date: str,
        day_of_week: str,
        fajr: str,
        sunrise: str,
        dhuhr: str,
        asr: str,
        maghrib: str,
        isha: str,
        is_special: bool = False,
        special_name_kk: str = None,
        special_name_ru: str = None,
    ):
        """Добавить/обновить запись расписания."""
        await self._conn.execute(
            "INSERT INTO ramadan_schedule "
            "(city, day_number, gregorian_date, day_of_week, fajr, sunrise, dhuhr, asr, maghrib, isha, "
            "is_special, special_name_kk, special_name_ru) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(city, day_number) DO UPDATE SET "
            "gregorian_date=?, day_of_week=?, fajr=?, sunrise=?, dhuhr=?, asr=?, maghrib=?, isha=?, "
            "is_special=?, special_name_kk=?, special_name_ru=?",
            (
                city, day_number, gregorian_date, day_of_week,
                fajr, sunrise, dhuhr, asr, maghrib, isha,
                is_special, special_name_kk, special_name_ru,
                gregorian_date, day_of_week,
                fajr, sunrise, dhuhr, asr, maghrib, isha,
                is_special, special_name_kk, special_name_ru,
            ),
        )
        await self._conn.commit()

    async def get_ramadan_schedule(self, city: str) -> list[dict]:
        """Получить расписание Рамадана для города."""
        cursor = await self._conn.execute(
            "SELECT * FROM ramadan_schedule WHERE city = ? ORDER BY day_number",
            (city,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_today_schedule(self, city: str, day_number: int) -> Optional[dict]:
        """Получить расписание на конкретный день."""
        cursor = await self._conn.execute(
            "SELECT * FROM ramadan_schedule WHERE city = ? AND day_number = ?",
            (city, day_number),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_schedule_count(self, city: str = None) -> int:
        """Количество записей расписания."""
        if city:
            cursor = await self._conn.execute(
                "SELECT COUNT(*) as cnt FROM ramadan_schedule WHERE city = ?", (city,)
            )
        else:
            cursor = await self._conn.execute(
                "SELECT COUNT(*) as cnt FROM ramadan_schedule"
            )
        row = await cursor.fetchone()
        return row["cnt"]

    # ──────────────────────── Moderator Tickets ────────────────────────

    async def create_moderator_ticket(
        self, user_telegram_id: int, message_text: str
    ) -> int:
        """Создать тикет для модератора. Возвращает ID."""
        cursor = await self._conn.execute(
            "INSERT INTO moderator_tickets (user_telegram_id, message_text) VALUES (?, ?)",
            (user_telegram_id, message_text),
        )
        await self._conn.commit()
        logger.info(f"Moderator ticket created: user={user_telegram_id}, id={cursor.lastrowid}")
        return cursor.lastrowid

    async def get_moderator_ticket(self, ticket_id: int) -> Optional[dict]:
        """Получить тикет по ID."""
        cursor = await self._conn.execute(
            "SELECT t.*, u.username, u.first_name FROM moderator_tickets t "
            "LEFT JOIN users u ON t.user_telegram_id = u.telegram_id "
            "WHERE t.id = ?",
            (ticket_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_pending_tickets(self, limit: int = 20) -> list[dict]:
        """Получить очередь ожидающих тикетов."""
        cursor = await self._conn.execute(
            "SELECT t.*, u.username, u.first_name FROM moderator_tickets t "
            "LEFT JOIN users u ON t.user_telegram_id = u.telegram_id "
            "WHERE t.status = 'pending' "
            "ORDER BY t.created_at ASC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def answer_ticket(
        self, ticket_id: int, response_text: str
    ) -> Optional[dict]:
        """Ответить на тикет. Возвращает обновлённую запись."""
        await self._conn.execute(
            "UPDATE moderator_tickets SET moderator_response = ?, status = 'answered', "
            "responded_at = CURRENT_TIMESTAMP WHERE id = ?",
            (response_text, ticket_id),
        )
        await self._conn.commit()
        return await self.get_moderator_ticket(ticket_id)

    async def get_ticket_stats(self) -> dict:
        """Статистика тикетов модератора."""
        stats = {}
        for status in ("pending", "answered"):
            cursor = await self._conn.execute(
                "SELECT COUNT(*) as cnt FROM moderator_tickets WHERE status = ?",
                (status,),
            )
            row = await cursor.fetchone()
            stats[status] = row["cnt"]
        cursor = await self._conn.execute("SELECT COUNT(*) as cnt FROM moderator_tickets")
        row = await cursor.fetchone()
        stats["total"] = row["cnt"]
        return stats

    # ──────────────────────── Kaspi Payments ────────────────────────

    async def create_kaspi_payment(
        self,
        user_telegram_id: int,
        amount: float,
        plan_days: int = 30,
    ) -> int:
        """Создать запись Kaspi-платежа. Возвращает ID."""
        cursor = await self._conn.execute(
            "INSERT INTO kaspi_payments "
            "(user_telegram_id, amount_expected, plan_days) "
            "VALUES (?, ?, ?)",
            (user_telegram_id, amount, plan_days),
        )
        await self._conn.commit()
        logger.info(f"Kaspi payment created: user={user_telegram_id}, id={cursor.lastrowid}")
        return cursor.lastrowid

    async def get_pending_kaspi_payment(self, user_telegram_id: int) -> Optional[dict]:
        """Получить последний pending Kaspi-платёж пользователя."""
        cursor = await self._conn.execute(
            "SELECT * FROM kaspi_payments "
            "WHERE user_telegram_id = ? AND status = 'pending' "
            "ORDER BY created_at DESC LIMIT 1",
            (user_telegram_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_kaspi_payment(
        self,
        payment_id: int,
        amount_found: float = None,
        comment_found: str = None,
        receipt_file_id: str = None,
        status: str = None,
    ):
        """Обновить данные Kaspi-платежа."""
        updates = []
        params = []
        if amount_found is not None:
            updates.append("amount_found = ?")
            params.append(amount_found)
        if comment_found is not None:
            updates.append("comment_found = ?")
            params.append(comment_found)
        if receipt_file_id is not None:
            updates.append("receipt_file_id = ?")
            params.append(receipt_file_id)
        if status is not None:
            updates.append("status = ?")
            params.append(status)
            if status in ("auto_approved", "approved", "rejected"):
                updates.append("verified_at = CURRENT_TIMESTAMP")
                if status == "auto_approved":
                    updates.append("verified_by = 'auto'")

        if not updates:
            return

        params.append(payment_id)
        await self._conn.execute(
            f"UPDATE kaspi_payments SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        await self._conn.commit()

    async def get_kaspi_payments_for_review(
        self, page: int = 1, per_page: int = 20, status: str = "all"
    ) -> tuple[list[dict], int]:
        """Список Kaspi-платежей для админки."""
        offset = (page - 1) * per_page
        where = []
        params = []

        if status != "all":
            where.append("k.status = ?")
            params.append(status)

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        count_sql = f"SELECT COUNT(*) as cnt FROM kaspi_payments k {where_sql}"
        cursor = await self._conn.execute(count_sql, params)
        total = (await cursor.fetchone())["cnt"]

        data_sql = (
            f"SELECT k.*, u.username, u.first_name "
            f"FROM kaspi_payments k "
            f"LEFT JOIN users u ON k.user_telegram_id = u.telegram_id "
            f"{where_sql} ORDER BY k.created_at DESC LIMIT ? OFFSET ?"
        )
        cursor = await self._conn.execute(data_sql, params + [per_page, offset])
        items = [dict(row) for row in await cursor.fetchall()]
        return items, total

    async def approve_kaspi_payment(self, payment_id: int, admin_username: str):
        """Подтвердить Kaspi-платёж (админом)."""
        await self._conn.execute(
            "UPDATE kaspi_payments SET status = 'approved', verified_by = ?, "
            "verified_at = CURRENT_TIMESTAMP WHERE id = ?",
            (admin_username, payment_id),
        )
        await self._conn.commit()
        logger.info(f"Kaspi payment #{payment_id} approved by {admin_username}")

    async def reject_kaspi_payment(self, payment_id: int, admin_username: str):
        """Отклонить Kaspi-платёж и отозвать подписку."""
        cursor = await self._conn.execute(
            "SELECT user_telegram_id FROM kaspi_payments WHERE id = ?",
            (payment_id,),
        )
        row = await cursor.fetchone()
        if row:
            await self.revoke_subscription(row["user_telegram_id"])

        await self._conn.execute(
            "UPDATE kaspi_payments SET status = 'rejected', verified_by = ?, "
            "verified_at = CURRENT_TIMESTAMP WHERE id = ?",
            (admin_username, payment_id),
        )
        await self._conn.commit()
        logger.info(f"Kaspi payment #{payment_id} rejected by {admin_username}")
