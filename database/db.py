"""
Асинхронная работа с SQLite через aiosqlite.
Управление пользователями, логами запросов, подписками,
историей диалогов, устаз-консультациями.
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
        logger.info(f"Database connected: {self.db_path} (WAL mode)")

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

    # ──────────────────────── Subscriptions ────────────────────────

    async def grant_subscription(
        self,
        telegram_id: int,
        plan_name: str = "manual",
        days: int = 30,
        amount: float = 0,
        currency: str = "KZT",
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
            "(user_telegram_id, plan_name, amount, currency, expires_at, payment_method, payment_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (telegram_id, plan_name, amount, currency, expires_at.isoformat(), payment_method, payment_id),
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
