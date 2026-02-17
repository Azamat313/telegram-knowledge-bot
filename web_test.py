"""
Веб-интерфейс для тестирования бота без Telegram.
Запуск: python web_test.py
Откройте http://localhost:8080 в браузере.
"""

import asyncio
import json
import os
import sys
import time

from aiohttp import web
from loguru import logger

sys.path.insert(0, os.path.dirname(__file__))

from config import CACHE_THRESHOLD, FREE_ANSWERS_LIMIT, OPENAI_MODEL
from core.normalizer import normalize_text
from core.search_engine import SearchEngine
from core.ai_engine import AIEngine
from core.knowledge_loader import load_all_knowledge

# HTML-страница с чат-интерфейсом
HTML_PAGE = r"""<!DOCTYPE html>
<html lang="kk">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Рамазан ИИ бот — Тест</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0e1621;
            color: #fff;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }
        .header {
            background: #17212b;
            padding: 16px 20px;
            border-bottom: 1px solid #242f3d;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .header .avatar {
            width: 42px; height: 42px;
            background: #3390ec;
            border-radius: 50%;
            display: flex; align-items: center; justify-content: center;
            font-size: 20px;
        }
        .header .info h2 { font-size: 16px; font-weight: 600; }
        .header .info span { font-size: 13px; color: #6c7883; }
        .chat {
            flex: 1;
            overflow-y: auto;
            padding: 16px 20px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .msg {
            max-width: 80%;
            padding: 10px 14px;
            border-radius: 12px;
            font-size: 15px;
            line-height: 1.45;
            word-wrap: break-word;
            white-space: pre-wrap;
        }
        .msg.bot {
            background: #182533;
            align-self: flex-start;
            border-bottom-left-radius: 4px;
        }
        .msg.user {
            background: #2b5278;
            align-self: flex-end;
            border-bottom-right-radius: 4px;
        }
        .msg .meta {
            font-size: 11px;
            color: #6c7883;
            margin-top: 8px;
            border-top: 1px solid #242f3d;
            padding-top: 6px;
        }
        .msg .source-tag {
            display: inline-block;
            background: #2b5278;
            color: #8ab4f8;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 11px;
            margin: 2px;
        }
        .msg .cache-tag {
            display: inline-block;
            background: #1b4332;
            color: #52b788;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 11px;
        }
        .msg .ai-tag {
            display: inline-block;
            background: #3d1f00;
            color: #fb8c00;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 11px;
        }
        .input-area {
            background: #17212b;
            padding: 12px 16px;
            border-top: 1px solid #242f3d;
            display: flex;
            gap: 10px;
        }
        .input-area input {
            flex: 1;
            background: #242f3d;
            border: none;
            border-radius: 22px;
            padding: 10px 18px;
            color: #fff;
            font-size: 15px;
            outline: none;
        }
        .input-area input::placeholder { color: #6c7883; }
        .input-area button {
            background: #3390ec;
            border: none;
            border-radius: 50%;
            width: 42px; height: 42px;
            cursor: pointer;
            display: flex; align-items: center; justify-content: center;
        }
        .input-area button:hover { background: #2b7fd4; }
        .input-area button svg { fill: #fff; width: 20px; height: 20px; }
        .input-area button:disabled { background: #555; cursor: not-allowed; }
        .stats-bar {
            background: #1c2938;
            padding: 8px 20px;
            font-size: 12px;
            color: #6c7883;
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
            border-bottom: 1px solid #242f3d;
        }
        .stats-bar span { color: #3390ec; }
        .typing { color: #6c7883; font-style: italic; padding: 8px 14px; }
    </style>
</head>
<body>
    <div class="header">
        <div class="avatar">&#9770;</div>
        <div class="info">
            <h2>Рамазан ИИ бот</h2>
            <span>Модель: <span id="model">...</span> | Кэш: <span id="cache-count">...</span></span>
        </div>
    </div>
    <div class="stats-bar">
        Ответов: <span id="stat-answered">0</span> |
        Из кэша: <span id="stat-cached">0</span> |
        Из ИИ: <span id="stat-ai">0</span> |
        Экономия: <span id="stat-savings">0%</span> |
        Время: <span id="stat-time">—</span>
    </div>
    <div class="chat" id="chat"></div>
    <div class="input-area">
        <input type="text" id="input" placeholder="Сұрақ жазыңыз / Задайте вопрос..." autocomplete="off">
        <button id="send-btn" onclick="send()">
            <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
        </button>
    </div>

    <script>
        let answered = 0, cached = 0, aiCount = 0;

        async function init() {
            const r = await fetch('/api/info');
            const d = await r.json();
            document.getElementById('model').textContent = d.model;
            document.getElementById('cache-count').textContent = d.cache_count;
            addMsg('bot', d.welcome);
        }

        function escHtml(s) {
            const d = document.createElement('div');
            d.textContent = s;
            return d.innerHTML;
        }

        function addMsg(type, text, data) {
            const chat = document.getElementById('chat');
            const div = document.createElement('div');
            div.className = 'msg ' + type;

            let html = escHtml(text);

            if (data) {
                html += '<div class="meta">';
                if (data.from_cache) {
                    html += '<span class="cache-tag">Кэш (similarity: ' + data.similarity.toFixed(4) + ')</span> ';
                } else {
                    html += '<span class="ai-tag">ИИ (' + data.model + ')</span> ';
                }
                if (data.sources) {
                    data.sources.split(', ').forEach(s => {
                        if (s) html += '<span class="source-tag">' + escHtml(s) + '</span> ';
                    });
                }
                if (data.time_ms) html += ' | ' + data.time_ms + 'ms';
                if (data.cost) html += ' | ~$' + data.cost;
                html += '</div>';
            }

            div.innerHTML = html;
            chat.appendChild(div);
            chat.scrollTop = chat.scrollHeight;
        }

        function removeTyping() {
            const t = document.getElementById('typing');
            if (t) t.remove();
        }

        function showTyping() {
            const chat = document.getElementById('chat');
            const div = document.createElement('div');
            div.id = 'typing';
            div.className = 'typing';
            div.textContent = 'ИИ думает...';
            chat.appendChild(div);
            chat.scrollTop = chat.scrollHeight;
        }

        function updateStats(fromCache, timeMs) {
            answered++;
            if (fromCache) cached++; else aiCount++;
            document.getElementById('stat-answered').textContent = answered;
            document.getElementById('stat-cached').textContent = cached;
            document.getElementById('stat-ai').textContent = aiCount;
            document.getElementById('stat-time').textContent = timeMs + 'ms';
            const pct = answered > 0 ? Math.round(cached / answered * 100) : 0;
            document.getElementById('stat-savings').textContent = pct + '%';
            document.getElementById('cache-count').textContent = parseInt(document.getElementById('cache-count').textContent || '0') + (fromCache ? 0 : 1);
        }

        async function send() {
            const input = document.getElementById('input');
            const btn = document.getElementById('send-btn');
            const text = input.value.trim();
            if (!text) return;
            input.value = '';
            btn.disabled = true;
            addMsg('user', text);
            showTyping();

            try {
                const r = await fetch('/api/ask', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({question: text})
                });
                const d = await r.json();
                removeTyping();
                addMsg('bot', d.answer, {
                    from_cache: d.from_cache,
                    similarity: d.similarity || 0,
                    sources: d.sources || '',
                    time_ms: d.time_ms,
                    model: d.model || '',
                    cost: d.estimated_cost || '',
                });
                updateStats(d.from_cache, d.time_ms);
            } catch(e) {
                removeTyping();
                addMsg('bot', 'Ошибка: ' + e.message);
            } finally {
                btn.disabled = false;
                input.focus();
            }
        }

        document.getElementById('input').addEventListener('keydown', e => {
            if (e.key === 'Enter') send();
        });

        init();
    </script>
</body>
</html>"""


async def handle_index(request):
    return web.Response(text=HTML_PAGE, content_type="text/html")


async def handle_info(request):
    app = request.app
    se: SearchEngine = app["search_engine"]
    return web.json_response({
        "model": OPENAI_MODEL,
        "cache_count": se.get_cache_count(),
        "kb_count": se.get_collection_count(),
        "welcome": (
            "Ассалаумағалейкум! Мен — Рамазан айына қатысты "
            "сұрақтарға жауап беретін ИИ бот-көмекшімін.\n\n"
            "Маған ораза, зекет, садақа, тарауих, пітір және т.б. "
            "тақырыптар бойынша сұрақ қойыңыз.\n\n"
            "Тест режимі — кэш/ИИ статус, источник, время и стоимость көрсетіледі."
        ),
    })


async def handle_ask(request):
    app = request.app
    data = await request.json()
    question = data.get("question", "").strip()

    if not question:
        return web.json_response({"error": "empty question"}, status=400)

    start_time = time.time()

    # Нормализация
    normalized = normalize_text(question)

    search_engine: SearchEngine = app["search_engine"]
    ai_engine: AIEngine = app["ai_engine"]

    # 1. Проверяем кэш
    cached = await search_engine.search_cache(normalized)

    if cached:
        elapsed_ms = int((time.time() - start_time) * 1000)
        response = {
            "answer": cached["answer"],
            "sources": cached.get("sources", ""),
            "from_cache": True,
            "similarity": cached["similarity"],
            "model": "cache",
            "time_ms": elapsed_ms,
            "estimated_cost": "$0",
        }
        logger.info(f"CACHE HIT: '{question[:60]}' | sim={cached['similarity']:.4f} | {elapsed_ms}ms")
        return web.json_response(response, dumps=lambda obj: json.dumps(obj, ensure_ascii=False))

    # 2. Ищем контекст в базе знаний
    context_results = await search_engine.search_context(normalized, n_results=5)

    # 3. ИИ-запрос с контекстом
    ai_result = await ai_engine.ask(question, context_results)
    elapsed_ms = int((time.time() - start_time) * 1000)

    if ai_result.get("answer"):
        sources_list = ai_result.get("sources", [])
        sources_str = ", ".join(sources_list) if sources_list else ""

        # Сохраняем в кэш
        await search_engine.cache_answer(
            question=normalized,
            answer=ai_result["answer"],
            sources=sources_str,
        )

        response = {
            "answer": ai_result["answer"],
            "sources": sources_str,
            "from_cache": False,
            "similarity": 1.0,
            "model": OPENAI_MODEL,
            "time_ms": elapsed_ms,
            "estimated_cost": "FREE",
        }
        logger.info(f"AI ANSWER: '{question[:60]}' | sources={sources_list} | {elapsed_ms}ms")
    else:
        response = {
            "answer": "Кешіріңіз, бұл сұрақ бойынша жауап таба алмадым.",
            "sources": "",
            "from_cache": False,
            "similarity": 0.0,
            "model": OPENAI_MODEL,
            "time_ms": elapsed_ms,
            "estimated_cost": "FREE",
        }
        logger.info(f"NO ANSWER: '{question[:60]}' | {elapsed_ms}ms")

    return web.json_response(response, dumps=lambda obj: json.dumps(obj, ensure_ascii=False))


async def handle_clear_cache(request):
    """Очистка кэша (для тестирования)."""
    app = request.app
    app["search_engine"].clear_cache()
    return web.json_response({"status": "cache cleared"})


async def init_app():
    app = web.Application()

    # Инициализация поискового + кэш-движка
    logger.info("Initializing search engine...")
    search_engine = SearchEngine()
    search_engine.init()

    # Загрузка базы знаний если пустая
    if search_engine.get_collection_count() == 0:
        logger.info("Loading knowledge base...")
        doc_count = load_all_knowledge(search_engine)
        logger.info(f"Knowledge base loaded: {doc_count} documents")
    else:
        logger.info(f"Knowledge base: {search_engine.get_collection_count()} documents")

    logger.info(f"Cache: {search_engine.get_cache_count()} cached answers")

    # Инициализация ИИ-движка (Gemini)
    logger.info("Initializing AI engine (Gemini)...")
    ai_engine = AIEngine()

    if not ai_engine.is_available():
        logger.error("AI engine not available! Check OPENAI_API_KEY in .env")

    app["search_engine"] = search_engine
    app["ai_engine"] = ai_engine

    # Роуты
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/info", handle_info)
    app.router.add_post("/api/ask", handle_ask)
    app.router.add_post("/api/clear-cache", handle_clear_cache)

    return app


def main():
    logger.remove()
    logger.add(sys.stderr, level="INFO")

    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting web test server on http://localhost:{port}")

    web.run_app(init_app(), host="0.0.0.0", port=port, print=lambda msg: logger.info(msg))


if __name__ == "__main__":
    main()
