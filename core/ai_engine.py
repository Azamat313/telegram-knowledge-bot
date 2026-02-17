"""
ИИ-движок: OpenAI ChatGPT + локальный контекст из базы знаний.
Используется openai SDK (async).

Особенности:
- "Білесіз бе?" suggestions после каждого ответа
- Строгая фильтрация off-topic вопросов
- Сигнализация неуверенности через маркер [СЕНІМСІЗ]
"""

import asyncio
import re

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
    "6. OFF-TOPIC ЕРЕЖЕСІ (ҚАТАҢ):\n"
    "   - Егер сұрақ Рамазанға, оразаға, ибадатқа, исламға МҮЛДЕМ қатысы жоқ болса "
    "(мысалы: спорт, ауа-райы, саясат, ойын-сауық, технология), "
    "жауаптың бірінші жолында [OFF_TOPIC] деп жаз, содан кейін:\n"
    "     Қазақша: 'Бұл сұрақтың оразаға қатысы жоқ. Мен тек Рамазан тақырыбы бойынша жауап беремін.'\n"
    "     Орысша: 'Этот вопрос не относится к Рамадану. Я отвечаю только на вопросы о Рамадане.'\n"
    "   - Егер сұрақ ислам тақырыбына жататын, бірақ тікелей Рамазанға қатысты болмаса "
    "(мысалы: намаз, зекет, қажылық, неке), жауап бер, бірақ Рамазанмен байланыстыр.\n"
    "7. Ешқашан діни фетуа берме, тек кітаптар мен хадистердегі ақпаратты жеткіз.\n"
    "8. Контексте кітап аты, автор немесе бет нөмірі берілсе, жауаптың соңында міндетті түрде көрсет:\n"
    "   Қазақша: 📖 Дереккөз: \"Кітап аты\", Автор, б. 123\n"
    "   Орысша: 📖 Источник: \"Название книги\", Автор, с. 123\n"
    "9. Сілтемелерді (URL) жауапқа ЕШҚАШАН қоспа. Жауапта тек мәтін болсын.\n"
    "10. СЕНІМДІЛІК ЕРЕЖЕСІ:\n"
    "   - Егер жауапқа СЕНІМДІ ЕМЕС болсаң (контекстте тікелей жауап жоқ, өз біліміңмен жауап бердің), "
    "жауаптың соңына жаңа жолда [СЕНІМСІЗ] деп жаз.\n"
    "   - Егер контексттен тікелей жауап тапсаң, [СЕНІМСІЗ] жазбай-ақ қой.\n"
    "11. ҰСЫНЫСТАР — ӘР ЖАУАПТЫҢ СОҢЫНДА МІНДЕТТІ:\n"
    "   Жауаптың ең соңғы бөлігі МІНДЕТТІ түрде [SUGGESTIONS] болуы тиіс.\n"
    "   Дәл осы форматты қолдан:\n\n"
    "   [SUGGESTIONS]\n"
    "   💡 Бірінші ұсынылатын сұрақ?\n"
    "   💡 Екінші ұсынылатын сұрақ?\n"
    "   💡 Үшінші ұсынылатын сұрақ?\n\n"
    "   Ережелер:\n"
    "   - [SUGGESTIONS] маркерін МІНДЕТТІ түрде жаз, оны ұмытпа!\n"
    "   - Әрбір ұсыныс 💡 белгісінен басталсын.\n"
    "   - 2-3 сұрақ жаз, тақырыпқа қатысты.\n"
    "   - Сұрақ тілінде жаз (қазақша/орысша).\n"
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
        author = r.get("author", "")
        book_title = r.get("book_title", "")
        page = r.get("page", "")
        source_url = r.get("source_url", "")

        part = f"[{i}] Дереккөз: {source}\n"
        if book_title:
            part += f"Кітап: {book_title}\n"
        if author:
            part += f"Автор: {author}\n"
        if page:
            part += f"Бет: {page}\n"
        part += f"Сұрақ: {question}\nЖауап: {answer}"
        parts.append(part)
    return "\n\n".join(parts)


def parse_ai_response(answer_text: str) -> dict:
    """
    Парсит ответ ИИ, извлекая маркеры:
    - [OFF_TOPIC] — вопрос не по теме
    - [СЕНІМСІЗ] — ИИ не уверен в ответе
    - [SUGGESTIONS] — предложения "Білесіз бе?"

    Returns:
        {
            "answer": str (чистый текст без маркеров),
            "is_off_topic": bool,
            "is_uncertain": bool,
            "suggestions": list[str],
        }
    """
    is_off_topic = "[OFF_TOPIC]" in answer_text
    is_uncertain = "[СЕНІМСІЗ]" in answer_text

    # Нормализуем маркер [SUGGESTIONS] (AI иногда пишет кириллическую С вместо латинской)
    normalized_text = re.sub(
        r'\[[СC][Uu][Gg][Gg][Ee][Ss][Tt][Ii][Oo][Nn][Ss]\]',
        '[SUGGESTIONS]',
        answer_text,
    )

    # Извлекаем suggestions
    suggestions = []
    if "[SUGGESTIONS]" in normalized_text:
        parts = normalized_text.split("[SUGGESTIONS]", 1)
        answer_clean = parts[0].strip()
        suggestions_text = parts[1].strip() if len(parts) > 1 else ""

        for line in suggestions_text.split("\n"):
            line = line.strip()
            if line.startswith("💡"):
                suggestion = line.lstrip("💡").strip()
                if suggestion:
                    suggestions.append(suggestion)
    else:
        # Fallback: ищем строки с 💡 в конце ответа
        answer_clean = normalized_text
        lines = normalized_text.split("\n")
        tail_suggestions = []
        for line in reversed(lines):
            stripped = line.strip()
            if stripped.startswith("💡"):
                suggestion = stripped.lstrip("💡").strip()
                if suggestion:
                    tail_suggestions.append(suggestion)
            elif stripped and tail_suggestions:
                break
        if tail_suggestions:
            tail_suggestions.reverse()
            suggestions = tail_suggestions
            clean_lines = [l for l in lines if not l.strip().startswith("💡")]
            answer_clean = "\n".join(clean_lines).strip()

    # Убираем все оставшиеся маркеры из текста
    answer_clean = answer_clean.replace("[OFF_TOPIC]", "").replace("[СЕНІМСІЗ]", "")
    # Чистим любые оставшиеся варианты [SUGGESTIONS]
    answer_clean = re.sub(
        r'\[[СC][Uu][Gg][Gg][Ee][Ss][Tt][Ii][Oo][Nn][Ss]\]', '', answer_clean
    ).strip()

    return {
        "answer": answer_clean,
        "is_off_topic": is_off_topic,
        "is_uncertain": is_uncertain,
        "suggestions": suggestions[:3],  # Максимум 3
    }


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
        lang: str = "kk",
    ) -> dict:
        """
        Отправляет вопрос + контекст из базы знаний в ChatGPT.

        Args:
            question: вопрос пользователя
            context_results: результаты поиска из ChromaDB (топ-5)
            conversation_history: история диалога [{role, message_text}]
            lang: язык пользователя (kk/ru)

        Returns:
            {
                "answer": str,
                "sources": list[str],
                "source_urls": list[str],
                "from_ai": True,
                "is_off_topic": bool,
                "is_uncertain": bool,
                "suggestions": list[str],
            }
        """
        if not self.is_available():
            logger.error("AI engine not available")
            return {
                "answer": None, "sources": [], "source_urls": [],
                "from_ai": True, "is_off_topic": False,
                "is_uncertain": False, "suggestions": [],
            }

        context = _build_context(context_results)
        sources = list({r.get("source", "") for r in context_results if r.get("source")})
        source_urls = list({
            r.get("source_url", "") for r in context_results
            if r.get("source_url")
        })

        # Строим messages для ChatGPT
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        # Добавляем историю диалога
        if conversation_history:
            for msg in conversation_history[-20:]:  # Последние 20 сообщений
                role = "user" if msg["role"] == "user" else "assistant"
                messages.append({"role": role, "content": msg["message_text"]})

        # Выбираем язык инструкции
        if lang == "ru":
            lang_instruction = (
                "ВАЖНО: Пользователь предпочитает русский язык. "
                "Отвечай на русском, если вопрос не задан явно на казахском."
            )
        else:
            lang_instruction = (
                "МАҢЫЗДЫ: Пайдаланушы қазақ тілін таңдаған. "
                "Жауапты қазақша бер, егер сұрақ анық орысша болмаса."
            )

        # Формируем пользовательский запрос с контекстом
        user_prompt = (
            f"Контекст (база знаний):\n{context}\n\n"
            f"Пайдаланушы сұрағы: {question}\n\n"
            f"{lang_instruction}\n"
            f"Контекстті пайдаланып жауап бер. Егер диалог тарихы болса, контекстке сүйен.\n"
            f"Ережелердегі [SUGGESTIONS] бөлімін ұмытпа — жауаптың соңына міндетті түрде қос."
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
                return {
                    "answer": None, "sources": sources, "source_urls": source_urls,
                    "from_ai": True, "is_off_topic": False,
                    "is_uncertain": False, "suggestions": [],
                }

            # Парсим ответ
            parsed = parse_ai_response(answer_text)

            logger.info(
                f"AI answer: {len(parsed['answer'])} chars, "
                f"off_topic={parsed['is_off_topic']}, "
                f"uncertain={parsed['is_uncertain']}, "
                f"suggestions={len(parsed['suggestions'])}, "
                f"sources={sources}"
            )

            return {
                "answer": parsed["answer"],
                "sources": sources if not parsed["is_off_topic"] else [],
                "source_urls": source_urls if not parsed["is_off_topic"] else [],
                "from_ai": True,
                "is_off_topic": parsed["is_off_topic"],
                "is_uncertain": parsed["is_uncertain"],
                "suggestions": parsed["suggestions"],
            }

        except Exception as e:
            logger.error(f"AI engine error: {e}")
            return {
                "answer": None, "sources": [], "source_urls": [],
                "from_ai": True, "is_off_topic": False,
                "is_uncertain": False, "suggestions": [],
            }
