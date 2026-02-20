# Ramadan Telegram Bot — Project Guide

## What is this

Multi-bot Telegram ecosystem for Ramadan Q&A. 3 bots share one SQLite database:
- **User bot** (`main.py`) — AI-powered Q&A with knowledge base, subscriptions, prayer calendar
- **Ustaz bot** (`run_ustaz_bot.py`) — consultant queue for escalated questions
- **Moderator bot** (`run_moderator_bot.py`) — support ticket handling

There is also `main_both.py` — runs user + ustaz bots in one process (legacy, not used in production).

## Tech Stack

- **Python 3.11** on server
- **aiogram 3.13** — Telegram Bot API framework
- **OpenAI GPT** (`gpt-4o-mini`) — AI answer generation
- **ChromaDB** + **sentence-transformers** (`paraphrase-multilingual-MiniLM-L12-v2`) — vector search / caching
- **aiosqlite** — async SQLite (WAL mode)
- **aiohttp** — web admin panel & web simulator
- **loguru** — structured logging

## Server & Deployment

- **Server:** VPS `185.129.51.30` (Ubuntu), user `root`
- **Project path on server:** `/opt/telegram-knowledge-bot/`
- **Python venv on server:** `/opt/telegram-knowledge-bot/venv/`
- **Git remote:** GitHub (push from local Windows → pull on server)

### Systemd Services (4 services)

| Service | File on server | Command | Port |
|---------|---------------|---------|------|
| `ramadan-bot` | `/etc/systemd/system/ramadan-bot.service` | `python main.py` | — |
| `ustaz-bot` | `/etc/systemd/system/ustaz-bot.service` | `python run_ustaz_bot.py` | — |
| `moderator-bot` | `/etc/systemd/system/moderator-bot.service` | `python run_moderator_bot.py` | — |
| `web-admin` | `/etc/systemd/system/web-admin.service` | `python web_admin.py` | 8888 |

### Deploy Procedure

SSH credentials are in `.claude/secrets.md` (gitignored, never commit).
On Windows use **paramiko** (Python) for non-interactive SSH since sshpass is not available.

**Automated deploy from Claude Code (paramiko):**
```python
import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
pwd = ')ro!h' + chr(37) + 'qrBbdPJMj4='   # password from .claude/secrets.md
ssh.connect('185.129.51.30', username='root', password=pwd)
stdin, stdout, stderr = ssh.exec_command('cd /opt/telegram-knowledge-bot && git pull && systemctl restart ramadan-bot')
print(stdout.read().decode(), stderr.read().decode())
ssh.close()
```

**Services to restart after deploy:**
```bash
systemctl restart ramadan-bot      # user bot
systemctl restart ustaz-bot        # ustaz bot
systemctl restart moderator-bot    # moderator bot
systemctl restart web-admin        # web admin panel (port 8888)

# Check logs:
journalctl -u ramadan-bot -f --no-pager
journalctl -u web-admin -f --no-pager
```

### Web Endpoints

| URL | Service | Auth |
|-----|---------|------|
| `http://185.129.51.30:8888/` | Web Admin (web_admin.py) | Basic Auth (`WEB_ADMIN_USER`/`WEB_ADMIN_PASSWORD`) |
| `http://185.129.51.30:8080/` | Web Simulator (web_simulator.py) | Basic Auth (same creds) |

## Project Structure

```
telegram-knowledge-bot/
├── main.py                  # Entry: user bot (production)
├── run_ustaz_bot.py         # Entry: ustaz bot (production)
├── run_moderator_bot.py     # Entry: moderator bot (production)
├── main_both.py             # Entry: user+ustaz combined (legacy)
├── web_admin.py             # Web admin panel SPA (port 8888)
├── web_simulator.py         # Web chat simulator (port 8080)
├── config.py                # All env vars & message constants
├── requirements.txt         # Dependencies
├── .env                     # Secrets (NOT in git)
├── .env.example             # Template for .env
│
├── bot/                     # User bot module
│   ├── handlers/
│   │   ├── user.py          # Main Q&A handler (catch-all, must be LAST router)
│   │   ├── admin.py         # /admin_* commands
│   │   ├── subscription.py  # Telegram Stars payments
│   │   ├── consultation.py  # Ask ustaz flow (FSM)
│   │   ├── calendar.py      # Ramadan prayer calendar
│   │   ├── moderator_request.py  # Support ticket flow (FSM)
│   │   └── onboarding.py    # /start → language → city (FSM, must be FIRST router)
│   ├── middlewares/
│   │   ├── rate_limit.py    # RATE_LIMIT_PER_MINUTE requests/min
│   │   └── subscription_check.py  # Free tier enforcement
│   └── keyboards/
│       └── inline.py        # Subscription, answer, suggestion keyboards
│
├── ustaz_bot/               # Ustaz bot module
│   ├── handlers/
│   │   ├── auth.py          # /start registration check
│   │   └── ustaz.py         # /queue, take/answer/skip consultations (FSM)
│   ├── middlewares/
│   │   └── ustaz_auth.py    # Only registered active ustazs allowed
│   └── keyboards/
│       └── inline.py        # Take/Skip/Cancel buttons
│
├── moderator_bot/           # Moderator bot module
│   ├── handlers/
│   │   └── moderator.py     # /queue, /stats, take/answer tickets (FSM)
│   └── keyboards/
│       └── inline.py        # Take/Skip/Cancel buttons
│
├── core/                    # Shared business logic
│   ├── search_engine.py     # ChromaDB vector search + AI cache
│   ├── ai_engine.py         # OpenAI ChatGPT wrapper (system prompt, parsing)
│   ├── knowledge_loader.py  # Load JSON knowledge base into ChromaDB
│   ├── normalizer.py        # Kazakh Latin→Cyrillic, typo fix, text cleanup
│   ├── muftyat_api.py       # muftyat.kz API client (prayer times, cities)
│   ├── cities.py            # 36 Kazakh cities with coordinates
│   ├── messages.py          # Bi-lingual strings (kk/ru) with get_msg()
│   └── ramadan_calendar.py  # Ramadan dates (2026-02-19 to 2026-03-20), day calc
│
├── database/
│   ├── db.py                # Database class — all async methods
│   └── models.py            # CREATE_TABLES_SQL (10 tables)
│
├── knowledge/
│   └── knowledge_base.json  # Q&A pairs for vector search
│
├── scripts/
│   ├── load_knowledge.py    # Standalone KB loader
│   ├── rebuild_knowledge.py # Rebuild ChromaDB from scratch
│   ├── extract_pdf_knowledge.py  # Extract Q&A from PDF books
│   ├── backup_db.py         # SQLite backup
│   └── setup_openai.py      # Test OpenAI connection
│
├── chroma_db/               # ChromaDB data (NOT in git)
├── logs/                    # Log files (NOT in git)
└── venv/                    # Python venv (NOT in git)
```

## Database

SQLite at `./database/bot.db` (WAL mode). 10 tables:

| Table | Purpose |
|-------|---------|
| `users` | User profiles: telegram_id, username, first_name, answers_count, is_subscribed, subscription_expires_at, city, language (kk/ru), is_onboarded, city_lat/lng |
| `query_logs` | Every user question: query_text, normalized_text, matched_question, answer_text, similarity_score, was_answered |
| `subscriptions` | Payment history: plan_name, amount, currency (XTR), expires_at, payment_id |
| `conversation_history` | Chat context: role (user/assistant), message_text — auto-trimmed to CONVERSATION_HISTORY_LIMIT |
| `ustaz_profiles` | Consultant registry: telegram_id, is_active, total_answered |
| `consultations` | Escalated questions: status (pending/in_progress/answered), question_text, answer_text |
| `moderator_tickets` | Support tickets: status (pending/answered), message_text, moderator_response |
| `ustaz_usage` | Monthly limit tracking: user_telegram_id, month_year, used_count |
| `prayer_times_cache` | Cached namaz times from muftyat.kz API: lat, lng, date, fajr...isha |
| `ramadan_schedule` | 30-day schedule per city (legacy, mostly using prayer_times_cache now) |

All DB operations are in `database/db.py` as async methods of `Database` class. For custom SQL in web panels, access `db._conn` directly (pattern from `web_simulator.py` and `web_admin.py`).

## Config (config.py)

All settings from `.env` via `python-dotenv`. Key vars:

| Variable | Default | Description |
|----------|---------|-------------|
| `BOT_TOKEN` | — | User bot token |
| `USTAZ_BOT_TOKEN` | — | Ustaz bot token |
| `MODERATOR_BOT_TOKEN` | — | Moderator bot token |
| `ADMIN_IDS` | — | Comma-separated telegram IDs of admins |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o-mini` | GPT model |
| `DATABASE_PATH` | `./database/bot.db` | SQLite path |
| `CACHE_THRESHOLD` | `0.90` | Similarity threshold for cache hits |
| `FREE_ANSWERS_LIMIT` | `5` (prod: `50`) | Free tier answer count |
| `WARNING_AT` | `3` (prod: `45`) | Warning threshold |
| `RATE_LIMIT_PER_MINUTE` | `5` | Max requests/min per user |
| `USTAZ_MONTHLY_LIMIT` | `5` | Max ustaz questions/month per user |
| `CONVERSATION_HISTORY_LIMIT` | `50` | Max conversation messages stored |
| `WEB_ADMIN_USER` | `admin` | Web admin login |
| `WEB_ADMIN_PASSWORD` | — | Web admin password |
| `DOMAIN` | — | Domain for SSL/nginx |

`SUBSCRIPTION_PLANS` dict: monthly (50 XTR, 30d), yearly (500 XTR, 365d).

Message constants: `MSG_WELCOME`, `MSG_HELP`, `MSG_LIMIT_REACHED`, etc. — all in Kazakh, defined in `config.py`. Bi-lingual messages in `core/messages.py`.

## Key Architecture Patterns

### Q&A Flow
```
User question
  → normalize_text() (Kazakh Latin→Cyrillic, typos)
  → search_cache() — if hit (similarity > 0.90), return cached
  → search_context() — find relevant KB articles
  → ChatGPT with context + conversation_history
  → parse response (off_topic?, uncertain?, suggestions)
  → cache_answer() — store in ChromaDB for future
  → log_query() — store in query_logs
  → show answer + suggestion buttons + "Ask Ustaz" if uncertain
```

### Consultation Flow
```
User clicks "Ask Ustaz"
  → check subscription (subscribers only)
  → check monthly limit (USTAZ_MONTHLY_LIMIT)
  → FSM: collect question text
  → create_consultation(status=pending)
  → notify all active ustazs via ustaz_bot

Ustaz opens /queue
  → get_pending_consultations()
  → Take button → take_consultation(status=in_progress)
  → FSM: collect answer text
  → answer_consultation(status=answered)
  → deliver answer to user via user_bot
```

### Router Order (IMPORTANT)
In `main.py`, routers must be registered in this order:
1. `onboarding.router` — catches /start for new users (FSM priority)
2. `admin.router` — /admin_* commands
3. `subscription.router` — payment callbacks
4. `consultation.router` — ask ustaz flow
5. `calendar.router` — calendar handler
6. `moderator_request.router` — support tickets
7. `user.router` — **LAST** (catch-all for text messages)

### Web Admin (web_admin.py)
Single-file SPA with embedded HTML/CSS/JS. Dark theme. Uses `aiohttp` + Basic Auth.
- 7 SQL helper functions for queries not in Database class
- 16 API endpoints under `/api/admin/`
- Pages: Dashboard, Users, Consultations, Ustazs, Tickets, Logs, Settings

### Web Simulator (web_simulator.py)
Dual-panel chat simulator for testing without Telegram. Left = user bot, Right = ustaz bot.

## Languages

The bot supports **Kazakh** (kk, default) and **Russian** (ru). Language is selected during onboarding and stored in `users.language`. Bi-lingual messages are in `core/messages.py` via `get_msg(key, lang)`.

Text normalization handles:
- Kazakh Latin script (transliteration to Cyrillic)
- Common typos and abbreviations
- Mixed Cyrillic/Latin input

## Working Locally (Windows)

```bash
cd "C:\Users\tkulz\OneDrive\Рабочий стол\бот\telegram-knowledge-bot"
# Activate venv
venv\Scripts\activate
# Run user bot
python main.py
# Run web admin
python web_admin.py
```

## Files NOT in Git

`.gitignore` excludes: `.env`, `*.db`, `chroma_db/`, `logs/`, `backups/`, `venv/`, `__pycache__/`
