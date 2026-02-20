"""
Веб-симулятор двух ботов: пользовательский + устаз-бот.
Полная имитация Telegram-взаимодействия без реальных токенов.

Запуск: python web_simulator.py
Откройте http://localhost:8090 в браузере.
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime

from aiohttp import web
from loguru import logger

sys.path.insert(0, os.path.dirname(__file__))

import base64

from config import (
    OPENAI_MODEL, FREE_ANSWERS_LIMIT, WARNING_AT,
    USTAZ_MONTHLY_LIMIT, CONVERSATION_HISTORY_LIMIT,
    WEB_ADMIN_USER, WEB_ADMIN_PASSWORD,
    MSG_WELCOME, MSG_HELP, MSG_HISTORY_CLEARED,
    MSG_ASK_USTAZ_CONFIRM, MSG_ASK_USTAZ_LIMIT, MSG_ASK_USTAZ_SENT,
    MSG_USTAZ_WELCOME, MSG_USTAZ_QUEUE_EMPTY, MSG_USTAZ_ANSWER_SENT,
    MSG_CONSULTATION_ANSWER, MSG_USTAZ_NEW_QUESTION,
    MSG_WARNING,
)
from core.normalizer import normalize_text
from core.search_engine import SearchEngine
from core.ai_engine import AIEngine
from core.knowledge_loader import load_all_knowledge
from database.db import Database

# ──────────────────────────────────────────────────────────
# Симулированные пользователи
# ──────────────────────────────────────────────────────────
SIM_USERS = {
    1001: {"username": "ali_user", "first_name": "Әлі", "is_subscribed": True},
    1002: {"username": "aisha_free", "first_name": "Айша", "is_subscribed": False},
    1003: {"username": "daulet_sub", "first_name": "Дәулет", "is_subscribed": True},
}

SIM_USTAZS = {
    2001: {"username": "ustaz_karim", "first_name": "Кәрім устаз"},
    2002: {"username": "ustaz_aslan", "first_name": "Аслан устаз"},
}


# ──────────────────────────────────────────────────────────
# HTML-страница — двойная панель
# ──────────────────────────────────────────────────────────
HTML_PAGE = r"""<!DOCTYPE html>
<html lang="kk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Бот Симулятор — Пайдаланушы + Устаз</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#0a0f18; color:#fff; height:100vh; display:flex; flex-direction:column; overflow:hidden; }

.top-bar { background:#111927; padding:8px 16px; display:flex; align-items:center; gap:16px; border-bottom:1px solid #1e2d3d; flex-shrink:0; }
.top-bar h1 { font-size:15px; font-weight:600; color:#7cacf8; }
.top-bar .info { font-size:12px; color:#6c7883; }
.top-bar .info span { color:#3390ec; }

.panels { display:flex; flex:1; overflow:hidden; }

.panel { flex:1; display:flex; flex-direction:column; border-right:1px solid #1e2d3d; }
.panel:last-child { border-right:none; }

.panel-header { background:#17212b; padding:10px 14px; border-bottom:1px solid #242f3d; display:flex; align-items:center; gap:10px; flex-shrink:0; }
.panel-header .avatar { width:36px; height:36px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:16px; flex-shrink:0; }
.panel-header .av-user { background:#3390ec; }
.panel-header .av-ustaz { background:#2d8c5a; }
.panel-header .info h3 { font-size:14px; font-weight:600; }
.panel-header .info span { font-size:11px; color:#6c7883; }

.panel-controls { background:#111b27; padding:6px 10px; display:flex; gap:6px; flex-wrap:wrap; border-bottom:1px solid #242f3d; flex-shrink:0; }
.panel-controls select, .panel-controls button {
    background:#242f3d; border:1px solid #344254; color:#b0bec5; border-radius:6px;
    padding:4px 10px; font-size:12px; cursor:pointer;
}
.panel-controls button:hover { background:#2b5278; color:#fff; }
.panel-controls button.cmd { background:#1b3a2a; border-color:#2d6b48; color:#52b788; }
.panel-controls button.cmd:hover { background:#2d6b48; color:#fff; }

.chat { flex:1; overflow-y:auto; padding:10px 14px; display:flex; flex-direction:column; gap:6px; }
.msg { max-width:85%; padding:8px 12px; border-radius:10px; font-size:13.5px; line-height:1.4; word-wrap:break-word; white-space:pre-wrap; }
.msg.bot { background:#182533; align-self:flex-start; border-bottom-left-radius:3px; }
.msg.user { background:#2b5278; align-self:flex-end; border-bottom-right-radius:3px; }
.msg.system { background:#1a1a2e; color:#7cacf8; align-self:center; font-size:12px; border-radius:8px; text-align:center; }

.msg .meta { font-size:10px; color:#6c7883; margin-top:6px; border-top:1px solid #242f3d; padding-top:4px; }
.tag { display:inline-block; padding:1px 7px; border-radius:8px; font-size:10px; margin:1px; }
.tag-cache { background:#1b4332; color:#52b788; }
.tag-ai { background:#3d1f00; color:#fb8c00; }
.tag-mem { background:#1a1a3e; color:#7c7cf8; }
.tag-src { background:#2b5278; color:#8ab4f8; }

.inline-btn { display:inline-block; background:#2b5278; color:#7cacf8; padding:5px 14px; border-radius:8px; margin:3px 3px 0 0; cursor:pointer; font-size:12px; border:1px solid #3d6a94; }
.inline-btn:hover { background:#3d6a94; color:#fff; }
.inline-btn.green { background:#1b4332; color:#52b788; border-color:#2d6b48; }
.inline-btn.green:hover { background:#2d6b48; color:#fff; }
.inline-btn.red { background:#3d1a1a; color:#f87171; border-color:#5a2d2d; }
.inline-btn.red:hover { background:#5a2d2d; color:#fff; }

.input-area { background:#17212b; padding:8px 12px; border-top:1px solid #242f3d; display:flex; gap:8px; flex-shrink:0; }
.input-area input { flex:1; background:#242f3d; border:none; border-radius:18px; padding:8px 14px; color:#fff; font-size:13px; outline:none; }
.input-area input::placeholder { color:#6c7883; }
.input-area button { background:#3390ec; border:none; border-radius:50%; width:36px; height:36px; cursor:pointer; display:flex; align-items:center; justify-content:center; flex-shrink:0; }
.input-area button:hover { background:#2b7fd4; }
.input-area button:disabled { background:#444; cursor:not-allowed; }
.input-area button svg { fill:#fff; width:16px; height:16px; }

.typing { color:#6c7883; font-style:italic; padding:6px 12px; font-size:12px; }

.q-card { background:#182533; border:1px solid #242f3d; border-radius:10px; padding:10px; margin-bottom:8px; }
.q-card .q-header { font-size:11px; color:#6c7883; margin-bottom:4px; }
.q-card .q-text { font-size:13px; margin-bottom:6px; }
.q-card .q-ai { font-size:12px; color:#fb8c00; margin-bottom:6px; padding:6px; background:#1a1500; border-radius:6px; }
.q-card .q-context { font-size:11px; color:#7c7cf8; margin-bottom:6px; padding:6px; background:#12122a; border-radius:6px; max-height:80px; overflow-y:auto; }

.notification { position:fixed; top:16px; right:16px; background:#2d6b48; color:#fff; padding:10px 18px; border-radius:10px; font-size:13px; z-index:999; animation:fadeIn .3s; }
@keyframes fadeIn { from{opacity:0;transform:translateY(-10px)} to{opacity:1;transform:translateY(0)} }
</style>
</head>
<body>

<div class="top-bar">
    <h1>&#9770; Бот Симулятор</h1>
    <div class="info">
        Модель: <span id="g-model">...</span> |
        База: <span id="g-kb">...</span> |
        Кэш: <span id="g-cache">...</span> |
        Тарих лимит: <span>HIST_LIMIT</span>
    </div>
</div>

<div class="panels">
    <!-- ═══════ ЛЕВАЯ ПАНЕЛЬ: Пользовательский бот ═══════ -->
    <div class="panel">
        <div class="panel-header">
            <div class="avatar av-user">&#9770;</div>
            <div class="info">
                <h3>Рамазан ИИ бот</h3>
                <span>Пайдаланушы: <b id="cur-user-name">Әлі</b> (ID: <span id="cur-user-id">1001</span>)</span>
            </div>
        </div>
        <div class="panel-controls">
            <select id="user-select" onchange="switchUser()">
                <option value="1001">Әлі (подписчик)</option>
                <option value="1002">Айша (бесплатная)</option>
                <option value="1003">Дәулет (подписчик)</option>
            </select>
            <button class="cmd" onclick="userCmd('/start')">/start</button>
            <button class="cmd" onclick="userCmd('/help')">/help</button>
            <button class="cmd" onclick="userCmd('/stats')">/stats</button>
            <button class="cmd" onclick="userCmd('/clear')">/clear</button>
        </div>
        <div class="chat" id="user-chat"></div>
        <div class="input-area">
            <input type="text" id="user-input" placeholder="Сұрақ жазыңыз..." autocomplete="off">
            <button id="user-send" onclick="userSend()">
                <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
            </button>
        </div>
    </div>

    <!-- ═══════ ПРАВАЯ ПАНЕЛЬ: Устаз бот ═══════ -->
    <div class="panel">
        <div class="panel-header">
            <div class="avatar av-ustaz">&#128331;</div>
            <div class="info">
                <h3>Устаз панелі</h3>
                <span>Устаз: <b id="cur-ustaz-name">Кәрім устаз</b> (ID: <span id="cur-ustaz-id">2001</span>)</span>
            </div>
        </div>
        <div class="panel-controls">
            <select id="ustaz-select" onchange="switchUstaz()">
                <option value="2001">Кәрім устаз</option>
                <option value="2002">Аслан устаз</option>
            </select>
            <button class="cmd" onclick="ustazCmd('/start')">/start</button>
            <button class="cmd" onclick="ustazCmd('/queue')">/queue</button>
            <button class="cmd" onclick="ustazCmd('/mystats')">/mystats</button>
            <button onclick="refreshQueue()" style="background:#2b5278;color:#fff;">&#8635; Жаңарту</button>
        </div>
        <div class="chat" id="ustaz-chat"></div>
        <div class="input-area">
            <input type="text" id="ustaz-input" placeholder="Жауап жазыңыз..." autocomplete="off" disabled>
            <button id="ustaz-send" onclick="ustazSend()" disabled>
                <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
            </button>
        </div>
    </div>
</div>

<script>
const SIM_USERS = USER_DATA_PLACEHOLDER;
const SIM_USTAZS = USTAZ_DATA_PLACEHOLDER;

let curUserId = 1001;
let curUstazId = 2001;
let ustazAnsweringId = null; // consultation_id, который устаз сейчас отвечает
let pendingUstazQuestion = null; // query_log_id для кнопки "Устазға сұрақ"
let ustazQuestionMode = false; // true = поле ввода принимает вопрос для устаза

// ─── Утилиты ───
function esc(s) { const d=document.createElement('div'); d.textContent=s; return d.innerHTML; }

function addMsg(chatId, type, text, extra) {
    const chat = document.getElementById(chatId);
    const div = document.createElement('div');
    div.className = 'msg ' + type;
    let html = esc(text);
    if (extra) html += extra;
    div.innerHTML = html;
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
    return div;
}

function addSystem(chatId, text) { addMsg(chatId, 'system', text); }

function showTyping(chatId) {
    const chat = document.getElementById(chatId);
    const div = document.createElement('div');
    div.id = chatId + '-typing';
    div.className = 'typing';
    div.textContent = 'Жазуда...';
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
}

function removeTyping(chatId) {
    const t = document.getElementById(chatId + '-typing');
    if (t) t.remove();
}

function showNotification(text) {
    const n = document.createElement('div');
    n.className = 'notification';
    n.textContent = text;
    document.body.appendChild(n);
    setTimeout(() => n.remove(), 3000);
}

// ─── Переключение пользователей ───
function switchUser() {
    curUserId = parseInt(document.getElementById('user-select').value);
    const u = SIM_USERS[curUserId];
    document.getElementById('cur-user-name').textContent = u.first_name;
    document.getElementById('cur-user-id').textContent = curUserId;
    document.getElementById('user-chat').innerHTML = '';
    addSystem('user-chat', u.first_name + ' ретінде кірдіңіз (' + (u.is_subscribed ? 'жазылымшы' : 'тегін') + ')');
}

function switchUstaz() {
    curUstazId = parseInt(document.getElementById('ustaz-select').value);
    const u = SIM_USTAZS[curUstazId];
    document.getElementById('cur-ustaz-name').textContent = u.first_name;
    document.getElementById('cur-ustaz-id').textContent = curUstazId;
    document.getElementById('ustaz-chat').innerHTML = '';
    ustazAnsweringId = null;
    setUstazInput(false);
    addSystem('ustaz-chat', u.first_name + ' ретінде кірдіңіз');
}

function setUstazInput(enabled) {
    document.getElementById('ustaz-input').disabled = !enabled;
    document.getElementById('ustaz-send').disabled = !enabled;
    document.getElementById('ustaz-input').placeholder = enabled ? 'Жауабыңызды жазыңыз...' : 'Алдымен сұрақ алыңыз (/queue)';
}

// ─── API вызовы ───
async function api(url, body) {
    const r = await fetch(url, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
    });
    return await r.json();
}

// ─── ПОЛЬЗОВАТЕЛЬСКИЙ БОТ ───
async function userCmd(cmd) {
    addMsg('user-chat', 'user', cmd);
    const d = await api('/api/user/command', { user_id: curUserId, command: cmd });
    addMsg('user-chat', 'bot', d.text, d.extra_html || '');
}

async function userSend() {
    const input = document.getElementById('user-input');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';

    // Если в режиме вопроса устазу — отправляем вопрос устазу
    if (ustazQuestionMode) {
        await sendUstazQuestion(text);
        return;
    }

    addMsg('user-chat', 'user', text);
    showTyping('user-chat');
    document.getElementById('user-send').disabled = true;

    try {
        const d = await api('/api/user/ask', { user_id: curUserId, question: text });
        removeTyping('user-chat');

        let meta = '<div class="meta">';
        if (d.from_cache) meta += '<span class="tag tag-cache">Кэш (sim=' + (d.similarity||0).toFixed(3) + ')</span> ';
        else meta += '<span class="tag tag-ai">ChatGPT</span> ';
        if (d.has_history) meta += '<span class="tag tag-mem">Жады: ' + d.history_count + ' хабар</span> ';
        if (d.sources) meta += '<span class="tag tag-src">' + esc(d.sources) + '</span> ';
        if (d.time_ms) meta += d.time_ms + 'мс';
        meta += '</div>';

        // Кнопка "Устазға сұрақ"
        if (d.show_ustaz_btn && d.query_log_id) {
            meta += '<div style="margin-top:6px"><span class="inline-btn green" onclick="askUstazFlow(' + d.query_log_id + ')">&#128332; Устазға сұрақ қою</span></div>';
        }

        // Предупреждение о лимите
        if (d.warning) {
            meta += '<div style="margin-top:4px;color:#fb8c00;font-size:11px;">⚠️ ' + esc(d.warning) + '</div>';
        }

        addMsg('user-chat', 'bot', d.answer, meta);
    } catch(e) {
        removeTyping('user-chat');
        addMsg('user-chat', 'bot', 'Қате: ' + e.message);
    } finally {
        document.getElementById('user-send').disabled = false;
        input.focus();
    }
}

// Устазға сұрақ flow
async function askUstazFlow(queryLogId) {
    const d = await api('/api/user/ask_ustaz_check', { user_id: curUserId, query_log_id: queryLogId });
    if (d.error) {
        addMsg('user-chat', 'bot', d.error);
        return;
    }
    // Показываем подтверждение
    let html = '<div style="margin-top:6px">';
    html += '<span class="inline-btn green" onclick="confirmAskUstaz(' + queryLogId + ')">✅ Жіберу</span> ';
    html += '<span class="inline-btn red" onclick="cancelAskUstaz()">❌ Болдырмау</span>';
    html += '</div>';
    addMsg('user-chat', 'bot', d.text, html);
    pendingUstazQuestion = queryLogId;
}

async function confirmAskUstaz(queryLogId) {
    // Переключаем поле ввода в режим "вопрос устазу"
    ustazQuestionMode = true;
    pendingUstazQuestion = queryLogId;
    const input = document.getElementById('user-input');
    input.placeholder = '✍️ Устазға сұрағыңызды жазыңыз...';
    input.style.borderColor = '#2d6b48';
    input.focus();
    addMsg('user-chat', 'bot', 'Устазға сұрағыңызды төменгі жолаққа жазып жіберіңіз:');
}

function cancelAskUstaz() {
    addMsg('user-chat', 'system', 'Сұрақ жіберу тоқтатылды.');
    resetUserInput();
}

function resetUserInput() {
    ustazQuestionMode = false;
    pendingUstazQuestion = null;
    const input = document.getElementById('user-input');
    input.placeholder = 'Сұрақ жазыңыз...';
    input.style.borderColor = '';
}

async function sendUstazQuestion(text) {
    addMsg('user-chat', 'user', text);
    const d = await api('/api/user/send_to_ustaz', {
        user_id: curUserId,
        query_log_id: pendingUstazQuestion,
        question: text,
    });
    addMsg('user-chat', 'bot', d.text);
    resetUserInput();

    if (d.success) {
        showNotification('Жаңа сұрақ устаз кезегіне қосылды!');
    }
}

// ─── УСТАЗ БОТ ───
async function ustazCmd(cmd) {
    addMsg('ustaz-chat', 'user', cmd);
    const d = await api('/api/ustaz/command', { ustaz_id: curUstazId, command: cmd });
    if (d.html) {
        const chat = document.getElementById('ustaz-chat');
        const div = document.createElement('div');
        div.className = 'msg bot';
        div.innerHTML = d.html;
        chat.appendChild(div);
        chat.scrollTop = chat.scrollHeight;
    } else {
        addMsg('ustaz-chat', 'bot', d.text || '');
    }
}

async function refreshQueue() {
    await ustazCmd('/queue');
}

async function takeQuestion(consultationId) {
    const d = await api('/api/ustaz/take', { ustaz_id: curUstazId, consultation_id: consultationId });
    if (d.error) {
        addMsg('ustaz-chat', 'bot', d.error);
        return;
    }
    // Показываем полную информацию
    const chat = document.getElementById('ustaz-chat');
    const div = document.createElement('div');
    div.className = 'msg bot';
    div.innerHTML = d.html;
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;

    ustazAnsweringId = consultationId;
    setUstazInput(true);
    document.getElementById('ustaz-input').focus();
}

async function skipQuestion(consultationId) {
    addSystem('ustaz-chat', 'Сұрақ #' + consultationId + ' өткізілді');
}

async function cancelAnswer() {
    if (!ustazAnsweringId) return;
    const d = await api('/api/ustaz/cancel', { ustaz_id: curUstazId, consultation_id: ustazAnsweringId });
    addMsg('ustaz-chat', 'bot', d.text);
    ustazAnsweringId = null;
    setUstazInput(false);
}

async function ustazSend() {
    if (!ustazAnsweringId) return;
    const input = document.getElementById('ustaz-input');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';

    addMsg('ustaz-chat', 'user', text);

    const d = await api('/api/ustaz/answer', {
        ustaz_id: curUstazId,
        consultation_id: ustazAnsweringId,
        answer: text,
    });

    addMsg('ustaz-chat', 'bot', d.text);

    if (d.success && d.delivered_to) {
        // Показываем в чате пользователя если совпадает
        if (d.delivered_to == curUserId) {
            addMsg('user-chat', 'bot',
                '🕌 Устаздан жауап!\n\nСұрағыңыз: ' + esc(d.question) + '\n\nЖауап: ' + esc(text),
                '<div class="meta"><span class="tag" style="background:#2d6b48;color:#52b788;">Устаз жауабы</span></div>'
            );
        }
        showNotification('Жауап пайдаланушыға жеткізілді!');
    }

    ustazAnsweringId = null;
    setUstazInput(false);
}

// Enter = send
document.getElementById('user-input').addEventListener('keydown', e => { if (e.key==='Enter') userSend(); });
document.getElementById('ustaz-input').addEventListener('keydown', e => { if (e.key==='Enter') ustazSend(); });

// Инициализация
async function init() {
    const r = await fetch('/api/info');
    const d = await r.json();
    document.getElementById('g-model').textContent = d.model;
    document.getElementById('g-kb').textContent = d.kb_count;
    document.getElementById('g-cache').textContent = d.cache_count;

    addSystem('user-chat', 'Әлі (жазылымшы) ретінде кірдіңіз');
    addMsg('user-chat', 'bot', d.welcome);

    addSystem('ustaz-chat', 'Кәрім устаз ретінде кірдіңіз');
    addMsg('ustaz-chat', 'bot', 'Ассалаумағалейкум! /queue — кезекті көру');
}
init();
</script>
</body>
</html>"""


# ──────────────────────────────────────────────────────────
# API хендлеры
# ──────────────────────────────────────────────────────────

async def handle_index(request):
    page = HTML_PAGE.replace(
        'USER_DATA_PLACEHOLDER',
        json.dumps({str(k): v for k, v in SIM_USERS.items()}, ensure_ascii=False)
    ).replace(
        'USTAZ_DATA_PLACEHOLDER',
        json.dumps({str(k): v for k, v in SIM_USTAZS.items()}, ensure_ascii=False)
    ).replace(
        'HIST_LIMIT',
        str(CONVERSATION_HISTORY_LIMIT)
    )
    return web.Response(text=page, content_type="text/html")


async def handle_info(request):
    app = request.app
    se: SearchEngine = app["search_engine"]
    return web.json_response({
        "model": OPENAI_MODEL,
        "cache_count": se.get_cache_count(),
        "kb_count": se.get_collection_count(),
        "welcome": MSG_WELCOME,
    })


def _json(data):
    return web.json_response(data, dumps=lambda obj: json.dumps(obj, ensure_ascii=False))


# ─── Пользовательский бот: команды ───

async def handle_user_command(request):
    app = request.app
    data = await request.json()
    user_id = data["user_id"]
    cmd = data["command"]
    db: Database = app["db"]
    se: SearchEngine = app["search_engine"]

    sim = SIM_USERS.get(user_id, SIM_USERS[1001])
    await db.get_or_create_user(user_id, sim["username"], sim["first_name"])

    if cmd == "/start":
        return _json({"text": MSG_WELCOME})

    elif cmd == "/help":
        return _json({"text": MSG_HELP})

    elif cmd == "/clear":
        await db.clear_conversation_history(user_id)
        return _json({"text": MSG_HISTORY_CLEARED})

    elif cmd == "/stats":
        user = await db.get_user(user_id)
        is_sub = sim.get("is_subscribed", False)
        status = "Белсенді (жазылымшы)" if is_sub else "Жоқ (тегін)"
        usage = await db.get_ustaz_usage(user_id)
        text = (
            f"📊 Сіздің статистикаңыз:\n\n"
            f"Пайдаланылған жауаптар: {user['answers_count']}\n"
            f"Тегін лимит: {FREE_ANSWERS_LIMIT}\n"
            f"Жазылым: {status}\n"
            f"Устаз сұрақтары (бұл ай): {usage}/{USTAZ_MONTHLY_LIMIT}\n"
            f"База: {se.get_collection_count()} жазба\n"
            f"Кэш: {se.get_cache_count()} жауап"
        )
        return _json({"text": text})

    return _json({"text": "Белгісіз команда"})


# ─── Пользовательский бот: вопрос ───

async def handle_user_ask(request):
    app = request.app
    data = await request.json()
    user_id = data["user_id"]
    question = data["question"].strip()

    db: Database = app["db"]
    se: SearchEngine = app["search_engine"]
    ai: AIEngine = app["ai_engine"]
    sim = SIM_USERS.get(user_id, SIM_USERS[1001])

    await db.get_or_create_user(user_id, sim["username"], sim["first_name"])

    start_time = time.time()
    normalized = normalize_text(question)

    # Загружаем историю
    history = await db.get_conversation_history(user_id)
    has_history = len(history) > 0

    # Кэш (только без истории)
    from_cache = False
    similarity = 0.0
    if not has_history:
        cached = await se.search_cache(normalized)
        if cached:
            answer = cached["answer"]
            sources = cached.get("sources", "")
            similarity = cached["similarity"]
            from_cache = True

            log_id = await db.log_query(
                user_telegram_id=user_id, query_text=question,
                normalized_text=normalized, matched_question=cached.get("cached_question", ""),
                answer_text=answer, similarity_score=similarity, was_answered=True,
            )
            new_count = await db.increment_answers_count(user_id)
            await db.add_conversation_message(user_id, "user", question)
            await db.add_conversation_message(user_id, "assistant", answer)

            elapsed = int((time.time() - start_time) * 1000)
            warning = None
            is_sub = sim.get("is_subscribed", False)
            if not is_sub and WARNING_AT <= new_count < FREE_ANSWERS_LIMIT:
                remaining = FREE_ANSWERS_LIMIT - new_count
                warning = MSG_WARNING.format(remaining=remaining, limit=FREE_ANSWERS_LIMIT)

            return _json({
                "answer": answer, "sources": sources, "from_cache": True,
                "similarity": similarity, "time_ms": elapsed,
                "has_history": has_history, "history_count": len(history),
                "show_ustaz_btn": is_sub, "query_log_id": log_id,
                "warning": warning,
            })

    # Поиск контекста + AI
    context_results = await se.search_context(normalized, n_results=5)
    ai_result = await ai.ask(question, context_results, history if has_history else None)

    elapsed = int((time.time() - start_time) * 1000)

    if not ai_result.get("answer"):
        await db.log_query(
            user_telegram_id=user_id, query_text=question,
            normalized_text=normalized, similarity_score=0.0, was_answered=False,
        )
        return _json({"answer": "Кешіріңіз, жауап таба алмадым.", "time_ms": elapsed,
                       "from_cache": False, "has_history": has_history, "history_count": len(history),
                       "show_ustaz_btn": False})

    answer = ai_result["answer"]
    sources_list = ai_result.get("sources", [])
    sources_str = ", ".join(sources_list) if sources_list else ""

    if not has_history:
        await se.cache_answer(question=normalized, answer=answer, sources=sources_str)

    log_id = await db.log_query(
        user_telegram_id=user_id, query_text=question,
        normalized_text=normalized, matched_question="[AI generated]",
        answer_text=answer, similarity_score=1.0, was_answered=True,
    )
    new_count = await db.increment_answers_count(user_id)
    await db.add_conversation_message(user_id, "user", question)
    await db.add_conversation_message(user_id, "assistant", answer)

    is_sub = sim.get("is_subscribed", False)
    warning = None
    if not is_sub and WARNING_AT <= new_count < FREE_ANSWERS_LIMIT:
        remaining = FREE_ANSWERS_LIMIT - new_count
        warning = MSG_WARNING.format(remaining=remaining, limit=FREE_ANSWERS_LIMIT)

    return _json({
        "answer": answer, "sources": sources_str, "from_cache": False,
        "similarity": 1.0, "time_ms": elapsed,
        "has_history": has_history, "history_count": len(history) + 1,
        "show_ustaz_btn": is_sub, "query_log_id": log_id,
        "warning": warning,
    })


# ─── Устаз-кнопка: проверка ───

async def handle_ask_ustaz_check(request):
    app = request.app
    data = await request.json()
    user_id = data["user_id"]
    db: Database = app["db"]
    sim = SIM_USERS.get(user_id, SIM_USERS[1001])

    if not sim.get("is_subscribed"):
        return _json({"error": "Устазға сұрақ қою тек жазылымшыларға қол жетімді."})

    can_ask, remaining = await db.check_ustaz_limit(user_id)
    if not can_ask:
        return _json({"error": MSG_ASK_USTAZ_LIMIT.format(limit=USTAZ_MONTHLY_LIMIT)})

    text = MSG_ASK_USTAZ_CONFIRM.format(limit=USTAZ_MONTHLY_LIMIT, remaining=remaining)
    return _json({"text": text})


# ─── Устаз-кнопка: отправка ───

async def handle_send_to_ustaz(request):
    app = request.app
    data = await request.json()
    user_id = data["user_id"]
    query_log_id = data.get("query_log_id")
    question = data["question"].strip()
    db: Database = app["db"]

    # Проверяем лимит
    can_ask, remaining = await db.check_ustaz_limit(user_id)
    if not can_ask:
        return _json({"text": MSG_ASK_USTAZ_LIMIT.format(limit=USTAZ_MONTHLY_LIMIT), "success": False})

    # Собираем контекст
    history = await db.get_conversation_history(user_id, limit=10)
    context_parts = []
    for msg in history:
        role_label = "Пайдаланушы" if msg["role"] == "user" else "AI"
        context_parts.append(f"{role_label}: {msg['message_text'][:200]}")
    conversation_context = "\n".join(context_parts) if context_parts else None

    # AI-ответ из лога
    ai_answer = None
    if query_log_id:
        cursor = await db._conn.execute(
            "SELECT answer_text FROM query_logs WHERE id = ?", (query_log_id,)
        )
        row = await cursor.fetchone()
        if row:
            ai_answer = row["answer_text"]

    consultation_id = await db.create_consultation(
        user_telegram_id=user_id,
        question_text=question,
        ai_answer_text=ai_answer,
        conversation_context=conversation_context,
        query_log_id=query_log_id,
    )
    await db.increment_ustaz_usage(user_id)

    logger.info(f"[SIM] Consultation #{consultation_id} created by user {user_id}")
    return _json({"text": MSG_ASK_USTAZ_SENT, "success": True, "consultation_id": consultation_id})


# ─── Устаз бот: команды ───

async def handle_ustaz_command(request):
    app = request.app
    data = await request.json()
    ustaz_id = data["ustaz_id"]
    cmd = data["command"]
    db: Database = app["db"]

    ustaz = await db.get_ustaz(ustaz_id)

    if cmd == "/start":
        if ustaz and ustaz.get("is_active"):
            return _json({"text": MSG_USTAZ_WELCOME})
        else:
            return _json({"text": "Сіз устаз ретінде тіркелмегенсіз.\nӘкімшіге хабарласыңыз."})

    if not ustaz or not ustaz.get("is_active"):
        return _json({"text": "Сіз устаз ретінде тіркелмегенсіз."})

    if cmd == "/queue":
        # Проверяем активный
        active = await db.get_ustaz_in_progress(ustaz_id)
        if active:
            html = (
                f'<div class="q-card">'
                f'<div class="q-header">⚠️ Сізде белсенді сұрақ бар — #{active["id"]}</div>'
                f'<div class="q-text">{_esc(active["question_text"][:300])}</div>'
                f'<div><span class="inline-btn red" onclick="cancelAnswer()">❌ Болдырмау</span></div>'
                f'</div>'
            )
            return _json({"html": html})

        consultations = await db.get_pending_consultations(limit=10)
        if not consultations:
            return _json({"text": MSG_USTAZ_QUEUE_EMPTY})

        html = f'<div style="font-size:13px;margin-bottom:8px;">📋 Кезекте <b>{len(consultations)}</b> сұрақ:</div>'
        for c in consultations:
            user_name = c.get("first_name") or c.get("username") or str(c["user_telegram_id"])
            html += f'<div class="q-card">'
            html += f'<div class="q-header">#{c["id"]} | {_esc(user_name)} | {c["created_at"][:16]}</div>'
            html += f'<div class="q-text">{_esc(c["question_text"][:200])}</div>'
            if c.get("ai_answer_text"):
                html += f'<div class="q-ai">AI: {_esc(c["ai_answer_text"][:150])}...</div>'
            if c.get("conversation_context"):
                html += f'<div class="q-context">{_esc(c["conversation_context"][:300])}</div>'
            html += f'<div>'
            html += f'<span class="inline-btn green" onclick="takeQuestion({c["id"]})">✅ Қабылдау</span> '
            html += f'<span class="inline-btn" onclick="skipQuestion({c["id"]})">⏭ Өткізу</span>'
            html += f'</div></div>'

        return _json({"html": html})

    elif cmd == "/mystats":
        text = (
            f"📊 Менің статистикам:\n\n"
            f"Жалпы жауаптар: {ustaz['total_answered']}\n"
            f"Статус: {'Белсенді' if ustaz['is_active'] else 'Белсенді емес'}\n"
            f"Тіркелген: {ustaz['created_at'][:10]}"
        )
        return _json({"text": text})

    return _json({"text": "Белгісіз команда"})


def _esc(s):
    """HTML escape для серверной генерации."""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ─── Устаз: взять вопрос ───

async def handle_ustaz_take(request):
    app = request.app
    data = await request.json()
    ustaz_id = data["ustaz_id"]
    consultation_id = data["consultation_id"]
    db: Database = app["db"]

    # Проверяем активный
    active = await db.get_ustaz_in_progress(ustaz_id)
    if active:
        return _json({"error": "Сізде аяқталмаған сұрақ бар. Алдымен оған жауап беріңіз."})

    taken = await db.take_consultation(consultation_id, ustaz_id)
    if not taken:
        return _json({"error": "Бұл сұрақты басқа устаз алды."})

    consultation = await db.get_consultation(consultation_id)

    html = f'<div class="q-card">'
    html += f'<div class="q-header">✅ Сұрақ #{consultation_id} қабылданды!</div>'
    html += f'<div class="q-text"><b>Сұрақ:</b> {_esc(consultation["question_text"])}</div>'
    if consultation.get("ai_answer_text"):
        html += f'<div class="q-ai"><b>AI жауабы:</b>\n{_esc(consultation["ai_answer_text"][:500])}</div>'
    if consultation.get("conversation_context"):
        html += f'<div class="q-context"><b>Диалог тарихы:</b>\n{_esc(consultation["conversation_context"][:500])}</div>'
    html += f'<div style="margin-top:6px;font-size:12px;color:#52b788;">Жауабыңызды төменгі жолаққа жазыңыз</div>'
    html += f'<div><span class="inline-btn red" onclick="cancelAnswer()">❌ Болдырмау</span></div>'
    html += f'</div>'

    return _json({"html": html})


# ─── Устаз: ответить ───

async def handle_ustaz_answer(request):
    app = request.app
    data = await request.json()
    ustaz_id = data["ustaz_id"]
    consultation_id = data["consultation_id"]
    answer_text = data["answer"].strip()
    db: Database = app["db"]

    consultation = await db.answer_consultation(consultation_id, answer_text)
    if not consultation:
        return _json({"text": "Консультация табылмады.", "success": False})

    await db.update_ustaz_stats(ustaz_id)

    logger.info(f"[SIM] Ustaz {ustaz_id} answered consultation #{consultation_id}")

    return _json({
        "text": MSG_USTAZ_ANSWER_SENT,
        "success": True,
        "delivered_to": consultation["user_telegram_id"],
        "question": consultation["question_text"][:200],
    })


# ─── Устаз: отменить ───

async def handle_ustaz_cancel(request):
    app = request.app
    data = await request.json()
    consultation_id = data["consultation_id"]
    db: Database = app["db"]

    await db._conn.execute(
        "UPDATE consultations SET ustaz_telegram_id = NULL, status = 'pending', "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (consultation_id,),
    )
    await db._conn.commit()

    return _json({"text": "Сұрақ кезекке қайтарылды."})


# ──────────────────────────────────────────────────────────
# Инициализация и запуск
# ──────────────────────────────────────────────────────────

@web.middleware
async def security_headers_middleware(request, handler):
    """Add security headers to every response."""
    response = await handler(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response


@web.middleware
async def basic_auth_middleware(request, handler):
    """HTTP Basic Auth middleware для защиты веб-панели."""
    if not WEB_ADMIN_PASSWORD:
        return await handler(request)

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            username, password = decoded.split(":", 1)
            if username == WEB_ADMIN_USER and password == WEB_ADMIN_PASSWORD:
                logger.info(f"Auth OK: {request.remote} user={username}")
                return await handler(request)
        except Exception:
            pass

    logger.warning(f"Failed auth: {request.remote} path={request.path}")
    return web.Response(
        status=401,
        text="401 Unauthorized",
        headers={"WWW-Authenticate": 'Basic realm="Bot Admin Panel"'},
    )


async def init_app():
    app = web.Application(middlewares=[security_headers_middleware, basic_auth_middleware])

    # БД
    logger.info("Connecting to database...")
    db = Database()
    await db.connect()

    # Поисковый движок
    logger.info("Initializing search engine...")
    se = SearchEngine()
    se.init()

    if se.get_collection_count() == 0:
        logger.info("Loading knowledge base...")
        doc_count = load_all_knowledge(se)
        logger.info(f"Knowledge base loaded: {doc_count} documents")
    else:
        logger.info(f"Knowledge base: {se.get_collection_count()} documents")

    # AI движок
    logger.info("Initializing AI engine...")
    ai = AIEngine()
    if not ai.is_available():
        logger.error("AI engine not available! Check OPENAI_API_KEY")

    # Создаём симулированных пользователей в БД
    for uid, udata in SIM_USERS.items():
        user = await db.get_or_create_user(uid, udata["username"], udata["first_name"])
        if udata.get("is_subscribed"):
            is_sub = await db.check_subscription(uid)
            if not is_sub:
                await db.grant_subscription(uid, plan_name="sim_test", days=365)
                logger.info(f"Granted subscription to simulated user {uid}")

    # Создаём симулированных устазов
    for uid, udata in SIM_USTAZS.items():
        await db.add_ustaz(uid, udata["username"], udata["first_name"])
        logger.info(f"Registered simulated ustaz {uid}")

    app["db"] = db
    app["search_engine"] = se
    app["ai_engine"] = ai

    # Роуты
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/info", handle_info)

    # User bot API
    app.router.add_post("/api/user/command", handle_user_command)
    app.router.add_post("/api/user/ask", handle_user_ask)
    app.router.add_post("/api/user/ask_ustaz_check", handle_ask_ustaz_check)
    app.router.add_post("/api/user/send_to_ustaz", handle_send_to_ustaz)

    # Ustaz bot API
    app.router.add_post("/api/ustaz/command", handle_ustaz_command)
    app.router.add_post("/api/ustaz/take", handle_ustaz_take)
    app.router.add_post("/api/ustaz/answer", handle_ustaz_answer)
    app.router.add_post("/api/ustaz/cancel", handle_ustaz_cancel)

    async def on_shutdown(app):
        await app["db"].close()

    app.on_shutdown.append(on_shutdown)

    return app


def main():
    logger.remove()
    logger.add(sys.stderr, level="INFO")

    port = int(os.environ.get("SIM_PORT", 8090))
    logger.info(f"Starting bot simulator on http://localhost:{port}")
    logger.info("Left panel = User bot | Right panel = Ustaz bot")

    web.run_app(init_app(), host="0.0.0.0", port=port, print=lambda msg: logger.info(msg))


if __name__ == "__main__":
    main()
