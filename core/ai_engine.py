"""
ИИ-движок: OpenAI ChatGPT + локальный контекст из базы знаний.
Используется openai SDK (async).
"""

import asyncio

from openai import AsyncOpenAI
from loguru import logger

from config import OPENAI_API_KEY, OPENAI_MODEL

SYSTEM_PROMPT = (
    "Сен — Рамазан айына қатысты сұрақтарға жауап беретін білімді көмекшісің.\n\n"
    "Ережелер:\n"
    "1. Берілген контексттегі ақпаратқа БІРІНШІ КЕЗЕКТЕ сүйен. Контекстте тікелей жауап болса, оны қолдан.\n"
    "2. Егер контексттен толық жауап табылмаса, өз білімдеріңді қолданып жауап бер.\n"
    "3. Жауапты сұрақ тілінде бер (қазақша сұрақ — қазақша жауап, орысша сұрақ — орысша жауап).\n"
    "4. Жауап нақты, толық және түсінікті болсын.\n"
    "5. Аят немесе хадис келтірсең, дереккөзін көрсет.\n"
    "6. Тек Рамазан, ораза, ибадат, ислам тақырыптарына жауап бер. Басқа тақырыптарға: "
    "'Кешіріңіз, мен тек Рамазан және ислам тақырыптары бойынша жауап беремін.' деп жаз.\n"
    "7. Ешқашан діни фетуа берме, тек кітаптар мен хадистердегі ақпаратты жеткіз.\n"
)


def _build_context(search_results: list[dict]) -> str:
    """Формирует контекст из результатов поиска по базе знаний."""
    if not search_results:
        return "Контекст жоқ."

    parts = []
    for i, r in enumerate(search_results, 1):
        source = r.get("source", "")
        question = r.get("question", "")
        answer = r.get("answer", "")
        parts.append(
            f"[{i}] Дереккөз: {source}\n"
            f"Сұрақ: {question}\n"
            f"Жауап: {answer}"
        )
    return "\n\n".join(parts)


class AIEngine:
    def __init__(
        self,
        api_key: str = OPENAI_API_KEY,
        model_name: str = OPENAI_MODEL,
    ):
        self.model_name = model_name
        self._client = None
        self._semaphore = asyncio.Semaphore(20)

        if api_key:
            self._client = AsyncOpenAI(
                api_key=api_key,
                timeout=30.0,
                max_retries=3,
            )
            logger.info(f"AIEngine initialized: model={model_name}")
        else:
            logger.warning("OPENAI_API_KEY not set! AI engine disabled.")

    def is_available(self) -> bool:
        return self._client is not None

    async def ask(
        self,
        question: str,
        context_results: list[dict],
        conversation_history: list[dict] = None,
    ) -> dict:
        """
        Отправляет вопрос + контекст из базы знаний в ChatGPT.

        Args:
            question: вопрос пользователя
            context_results: результаты поиска из ChromaDB (топ-5)
            conversation_history: история диалога [{role, message_text}]

        Returns:
            {"answer": str, "sources": list[str], "from_ai": True}
        """
        if not self.is_available():
            logger.error("AI engine not available")
            return {"answer": None, "sources": [], "from_ai": True}

        context = _build_context(context_results)
        sources = list({r.get("source", "") for r in context_results if r.get("source")})

        # Строим messages для ChatGPT
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        # Добавляем историю диалога
        if conversation_history:
            for msg in conversation_history[-20:]:  # Последние 20 сообщений
                role = "user" if msg["role"] == "user" else "assistant"
                messages.append({"role": role, "content": msg["message_text"]})

        # Формируем пользовательский запрос с контекстом
        user_prompt = (
            f"Контекст (база знаний):\n{context}\n\n"
            f"Пайдаланушы сұрағы: {question}\n\n"
            f"МАҢЫЗДЫ: Жауапты сұрақ тілінде бер! Егер сұрақ орысша болса — орысша жауап бер. "
            f"Егер қазақша болса — қазақша жауап бер.\n"
            f"Контекстті пайдаланып жауап бер. Егер диалог тарихы болса, контекстке сүйен."
        )
        messages.append({"role": "user", "content": user_prompt})

        try:
            async with self._semaphore:
                response = await self._client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=0.3,
                )

            answer_text = None
            if response.choices and response.choices[0].message.content:
                answer_text = response.choices[0].message.content.strip()

            if not answer_text:
                logger.warning("ChatGPT returned empty response")
                return {"answer": None, "sources": sources, "from_ai": True}

            # Проверяем, не ответил ли ИИ что тема вне его области
            off_topic_markers = [
                "тек рамазан",
                "тек ислам тақырыптары",
                "мен тек рамазан",
            ]
            if any(m in answer_text.lower() for m in off_topic_markers):
                return {"answer": answer_text, "sources": [], "from_ai": True}

            logger.info(f"AI answer: {len(answer_text)} chars, sources={sources}")
            return {"answer": answer_text, "sources": sources, "from_ai": True}

        except Exception as e:
            logger.error(f"AI engine error: {e}")
            return {"answer": None, "sources": [], "from_ai": True}
