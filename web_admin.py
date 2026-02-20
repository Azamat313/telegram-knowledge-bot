"""
Веб-админка для Telegram Ramadan Bot.
SPA с тёмной темой — управление пользователями, подписками,
консультациями, тикетами, устазами, статистикой.
"""

import asyncio
import base64
import io
import json
import os
import sys

from aiohttp import web
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from loguru import logger

from config import (
    BOT_TOKEN,
    WEB_ADMIN_USER,
    WEB_ADMIN_PASSWORD,
    FREE_ANSWERS_LIMIT,
    WARNING_AT,
    RATE_LIMIT_PER_MINUTE,
    USTAZ_MONTHLY_LIMIT,
    CONVERSATION_HISTORY_LIMIT,
    OPENAI_MODEL,
    DATABASE_PATH,
    CACHE_THRESHOLD,
    SUBSCRIPTION_PLANS,
    DOMAIN,
    KASPI_PAY_LINK,
    KASPI_PRICE_KZT,
    KASPI_PLAN_DAYS,
)
from database.db import Database

ADMIN_PORT = int(os.getenv("ADMIN_PORT", "8888"))


# ══════════════════════════════════════════════════════════════════
#  Секция 2: SQL-хелперы
# ══════════════════════════════════════════════════════════════════


async def sql_list_users(db: Database, page: int = 1, per_page: int = 25,
                         search: str = "", filter_: str = "all"):
    """Список пользователей с пагинацией, поиском и фильтром."""
    offset = (page - 1) * per_page
    where = []
    params = []

    if search:
        where.append(
            "(u.username LIKE ? OR u.first_name LIKE ? OR CAST(u.telegram_id AS TEXT) LIKE ?)"
        )
        like = f"%{search}%"
        params.extend([like, like, like])

    if filter_ == "subscribed":
        where.append("u.is_subscribed = TRUE")
    elif filter_ == "free":
        where.append("u.is_subscribed = FALSE")

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    count_sql = f"SELECT COUNT(*) as cnt FROM users u {where_sql}"
    cursor = await db._conn.execute(count_sql, params)
    total = (await cursor.fetchone())["cnt"]

    data_sql = (
        f"SELECT u.id, u.telegram_id, u.username, u.first_name, "
        f"u.answers_count, u.is_subscribed, u.subscription_expires_at, "
        f"u.city, u.language, u.is_onboarded, u.created_at "
        f"FROM users u {where_sql} "
        f"ORDER BY u.created_at DESC LIMIT ? OFFSET ?"
    )
    cursor = await db._conn.execute(data_sql, params + [per_page, offset])
    items = [dict(row) for row in await cursor.fetchall()]
    return items, total


async def sql_list_consultations(db: Database, page: int = 1, per_page: int = 20,
                                 status: str = "all"):
    """Список консультаций с JOIN пользователей и устазов."""
    offset = (page - 1) * per_page
    where = []
    params = []

    if status != "all":
        where.append("c.status = ?")
        params.append(status)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    count_sql = f"SELECT COUNT(*) as cnt FROM consultations c {where_sql}"
    cursor = await db._conn.execute(count_sql, params)
    total = (await cursor.fetchone())["cnt"]

    data_sql = (
        f"SELECT c.id, c.user_telegram_id, c.ustaz_telegram_id, c.status, "
        f"SUBSTR(c.question_text, 1, 200) as question_text, "
        f"SUBSTR(c.answer_text, 1, 200) as answer_text, "
        f"c.created_at, c.answered_at, "
        f"u.username as user_username, u.first_name as user_first_name, "
        f"up.username as ustaz_username, up.first_name as ustaz_first_name "
        f"FROM consultations c "
        f"LEFT JOIN users u ON c.user_telegram_id = u.telegram_id "
        f"LEFT JOIN ustaz_profiles up ON c.ustaz_telegram_id = up.telegram_id "
        f"{where_sql} ORDER BY c.created_at DESC LIMIT ? OFFSET ?"
    )
    cursor = await db._conn.execute(data_sql, params + [per_page, offset])
    items = [dict(row) for row in await cursor.fetchall()]
    return items, total


async def sql_list_tickets(db: Database, page: int = 1, per_page: int = 20,
                           status: str = "all"):
    """Список тикетов с JOIN пользователей."""
    offset = (page - 1) * per_page
    where = []
    params = []

    if status != "all":
        where.append("t.status = ?")
        params.append(status)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    count_sql = f"SELECT COUNT(*) as cnt FROM moderator_tickets t {where_sql}"
    cursor = await db._conn.execute(count_sql, params)
    total = (await cursor.fetchone())["cnt"]

    data_sql = (
        f"SELECT t.id, t.user_telegram_id, t.status, "
        f"SUBSTR(t.message_text, 1, 200) as message_text, "
        f"SUBSTR(t.moderator_response, 1, 200) as moderator_response, "
        f"t.created_at, t.responded_at, "
        f"u.username, u.first_name "
        f"FROM moderator_tickets t "
        f"LEFT JOIN users u ON t.user_telegram_id = u.telegram_id "
        f"{where_sql} ORDER BY t.created_at DESC LIMIT ? OFFSET ?"
    )
    cursor = await db._conn.execute(data_sql, params + [per_page, offset])
    items = [dict(row) for row in await cursor.fetchall()]
    return items, total


async def sql_list_logs(db: Database, page: int = 1, per_page: int = 50,
                        filter_: str = "all"):
    """Недавние запросы с JOIN пользователей."""
    offset = (page - 1) * per_page
    where = []
    params = []

    if filter_ == "answered":
        where.append("q.was_answered = TRUE")
    elif filter_ == "unanswered":
        where.append("q.was_answered = FALSE")

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    count_sql = f"SELECT COUNT(*) as cnt FROM query_logs q {where_sql}"
    cursor = await db._conn.execute(count_sql, params)
    total = (await cursor.fetchone())["cnt"]

    data_sql = (
        f"SELECT q.id, q.user_telegram_id, "
        f"SUBSTR(q.query_text, 1, 200) as query_text, "
        f"SUBSTR(q.matched_question, 1, 200) as matched_question, "
        f"q.similarity_score, q.was_answered, q.created_at, "
        f"u.username, u.first_name "
        f"FROM query_logs q "
        f"LEFT JOIN users u ON q.user_telegram_id = u.telegram_id "
        f"{where_sql} ORDER BY q.created_at DESC LIMIT ? OFFSET ?"
    )
    cursor = await db._conn.execute(data_sql, params + [per_page, offset])
    items = [dict(row) for row in await cursor.fetchall()]
    return items, total


async def sql_get_user_detail(db: Database, telegram_id: int):
    """Подробная информация о пользователе."""
    cursor = await db._conn.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
    )
    row = await cursor.fetchone()
    if not row:
        return None

    user = dict(row)

    # Подписки
    cursor = await db._conn.execute(
        "SELECT * FROM subscriptions WHERE user_telegram_id = ? ORDER BY started_at DESC LIMIT 10",
        (telegram_id,),
    )
    user["subscriptions"] = [dict(r) for r in await cursor.fetchall()]

    # Последние консультации
    cursor = await db._conn.execute(
        "SELECT id, status, SUBSTR(question_text, 1, 200) as question_text, "
        "created_at, answered_at FROM consultations "
        "WHERE user_telegram_id = ? ORDER BY created_at DESC LIMIT 10",
        (telegram_id,),
    )
    user["consultations"] = [dict(r) for r in await cursor.fetchall()]

    # Последние запросы
    cursor = await db._conn.execute(
        "SELECT id, SUBSTR(query_text, 1, 200) as query_text, "
        "was_answered, similarity_score, created_at FROM query_logs "
        "WHERE user_telegram_id = ? ORDER BY created_at DESC LIMIT 20",
        (telegram_id,),
    )
    user["logs"] = [dict(r) for r in await cursor.fetchall()]

    return user


async def sql_list_all_ustazs(db: Database):
    """Все устазы (активные + неактивные)."""
    cursor = await db._conn.execute(
        "SELECT * FROM ustaz_profiles ORDER BY is_active DESC, created_at DESC"
    )
    return [dict(row) for row in await cursor.fetchall()]


async def sql_activate_ustaz(db: Database, telegram_id: int):
    """Реактивация устаза."""
    cursor = await db._conn.execute(
        "UPDATE ustaz_profiles SET is_active = TRUE, updated_at = CURRENT_TIMESTAMP "
        "WHERE telegram_id = ?",
        (telegram_id,),
    )
    await db._conn.commit()
    return cursor.rowcount > 0


# ══════════════════════════════════════════════════════════════════
#  Секция 3: API-хендлеры
# ══════════════════════════════════════════════════════════════════


def _json(data, status=200):
    return web.Response(
        text=json.dumps(data, ensure_ascii=False, default=str),
        content_type="application/json",
        status=status,
    )


# ─── Dashboard ───

async def handle_dashboard(request):
    db: Database = request.app["db"]
    total_users = await db.get_total_users()
    total_queries = await db.get_total_queries()
    answered = await db.get_answered_queries()
    subscribed = await db.get_subscribed_users()
    consultation_stats = await db.get_consultation_stats()
    ticket_stats = await db.get_ticket_stats()

    answered_pct = round(answered / total_queries * 100, 1) if total_queries else 0

    return _json({
        "total_users": total_users,
        "total_queries": total_queries,
        "answered_queries": answered,
        "answered_pct": answered_pct,
        "subscribed_users": subscribed,
        "consultation_stats": consultation_stats,
        "ticket_stats": ticket_stats,
    })


# ─── Users ───

async def handle_users_list(request):
    db: Database = request.app["db"]
    page = max(1, min(int(request.query.get("page", 1)), 10000))
    search = request.query.get("search", "")[:200]
    filter_ = request.query.get("filter", "all")
    items, total = await sql_list_users(db, page, 25, search, filter_)
    return _json({"items": items, "total": total, "page": page, "per_page": 25})


async def handle_user_detail(request):
    db: Database = request.app["db"]
    telegram_id = int(request.match_info["telegram_id"])
    user = await sql_get_user_detail(db, telegram_id)
    if not user:
        return _json({"error": "User not found"}, 404)
    return _json(user)


async def handle_user_grant(request):
    db: Database = request.app["db"]
    telegram_id = int(request.match_info["telegram_id"])
    body = await request.json()
    days = int(body.get("days", 30))
    plan = body.get("plan", "manual")
    await db.grant_subscription(telegram_id, plan_name=plan, days=days)
    return _json({"success": True, "message": f"Subscription granted for {days} days"})


async def handle_user_revoke(request):
    db: Database = request.app["db"]
    telegram_id = int(request.match_info["telegram_id"])
    await db.revoke_subscription(telegram_id)
    return _json({"success": True, "message": "Subscription revoked"})


# ─── Consultations ───

async def handle_consultations_list(request):
    db: Database = request.app["db"]
    page = max(1, min(int(request.query.get("page", 1)), 10000))
    status = request.query.get("status", "all")
    items, total = await sql_list_consultations(db, page, 20, status)
    return _json({"items": items, "total": total, "page": page, "per_page": 20})


async def handle_consultation_detail(request):
    db: Database = request.app["db"]
    cid = int(request.match_info["id"])
    c = await db.get_consultation(cid)
    if not c:
        return _json({"error": "Consultation not found"}, 404)
    return _json(c)


# ─── Ustazs ───

async def handle_ustazs_list(request):
    db: Database = request.app["db"]
    items = await sql_list_all_ustazs(db)
    return _json({"items": items})


async def handle_ustaz_add(request):
    db: Database = request.app["db"]
    body = await request.json()
    tid = int(body["telegram_id"])
    username = body.get("username", "")
    first_name = body.get("first_name", "")
    ustaz = await db.add_ustaz(tid, username=username, first_name=first_name)
    return _json({"success": True, "ustaz": ustaz})


async def handle_ustaz_deactivate(request):
    db: Database = request.app["db"]
    tid = int(request.match_info["id"])
    ok = await db.remove_ustaz(tid)
    return _json({"success": ok})


async def handle_ustaz_activate(request):
    db: Database = request.app["db"]
    tid = int(request.match_info["id"])
    ok = await sql_activate_ustaz(db, tid)
    return _json({"success": ok})


# ─── Tickets ───

async def handle_tickets_list(request):
    db: Database = request.app["db"]
    page = max(1, min(int(request.query.get("page", 1)), 10000))
    status = request.query.get("status", "all")
    items, total = await sql_list_tickets(db, page, 20, status)
    return _json({"items": items, "total": total, "page": page, "per_page": 20})


async def handle_ticket_detail(request):
    db: Database = request.app["db"]
    tid = int(request.match_info["id"])
    ticket = await db.get_moderator_ticket(tid)
    if not ticket:
        return _json({"error": "Ticket not found"}, 404)
    return _json(ticket)


async def handle_ticket_answer(request):
    db: Database = request.app["db"]
    tid = int(request.match_info["id"])
    body = await request.json()
    response = body.get("response", "")
    if not response.strip():
        return _json({"error": "Response cannot be empty"}, 400)
    ticket = await db.answer_ticket(tid, response)
    return _json({"success": True, "ticket": ticket})


# ─── Kaspi Payments ───

async def handle_kaspi_list(request):
    db: Database = request.app["db"]
    page = max(1, min(int(request.query.get("page", 1)), 10000))
    status = request.query.get("status", "all")
    items, total = await db.get_kaspi_payments_for_review(page, 20, status)
    return _json({"items": items, "total": total, "page": page, "per_page": 20})


async def handle_kaspi_approve(request):
    db: Database = request.app["db"]
    pid = int(request.match_info["id"])
    await db.approve_kaspi_payment(pid, WEB_ADMIN_USER)
    return _json({"success": True, "message": "Payment approved"})


async def handle_kaspi_reject(request):
    db: Database = request.app["db"]
    pid = int(request.match_info["id"])
    await db.reject_kaspi_payment(pid, WEB_ADMIN_USER)
    return _json({"success": True, "message": "Payment rejected, subscription revoked"})


async def handle_kaspi_receipt(request):
    """Download receipt image from Telegram and serve it."""
    db: Database = request.app["db"]
    bot: Bot = request.app["bot"]
    pid = int(request.match_info["id"])

    cursor = await db._conn.execute(
        "SELECT receipt_file_id FROM kaspi_payments WHERE id = ?", (pid,)
    )
    row = await cursor.fetchone()
    if not row or not row["receipt_file_id"]:
        return _json({"error": "Receipt not found"}, 404)

    file = await bot.get_file(row["receipt_file_id"])
    buf = io.BytesIO()
    await bot.download_file(file.file_path, buf)
    buf.seek(0)
    data = buf.read()

    ext = (file.file_path or "").rsplit(".", 1)[-1].lower()
    ct = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
          "webp": "image/webp"}.get(ext, "image/jpeg")

    return web.Response(body=data, content_type=ct)


# ─── Logs ───

async def handle_logs_list(request):
    db: Database = request.app["db"]
    page = max(1, min(int(request.query.get("page", 1)), 10000))
    filter_ = request.query.get("filter", "all")
    items, total = await sql_list_logs(db, page, 50, filter_)
    return _json({"items": items, "total": total, "page": page, "per_page": 50})


async def handle_logs_top_unanswered(request):
    db: Database = request.app["db"]
    items = await db.get_top_unanswered(limit=20)
    return _json({"items": items})


async def handle_logs_top_questions(request):
    db: Database = request.app["db"]
    items = await db.get_top_questions(limit=20)
    return _json({"items": items})


# ─── Broadcast ───

async def handle_broadcast(request):
    db: Database = request.app["db"]
    bot: Bot = request.app["bot"]
    body = await request.json()
    message = body.get("message", "").strip()
    if not message:
        return _json({"error": "Message cannot be empty"}, 400)

    cursor = await db._conn.execute(
        "SELECT telegram_id FROM users WHERE is_onboarded = TRUE"
    )
    rows = await cursor.fetchall()
    user_ids = [row["telegram_id"] for row in rows]

    total = len(user_ids)
    sent = 0
    failed = 0
    errors = []

    for i, tid in enumerate(user_ids):
        try:
            await bot.send_message(tid, message, parse_mode=ParseMode.HTML)
            sent += 1
        except Exception as e:
            failed += 1
            errors.append({"telegram_id": tid, "error": str(e)})
        if (i + 1) % 25 == 0:
            await asyncio.sleep(1)

    logger.info(f"Broadcast: total={total}, sent={sent}, failed={failed}")
    return _json({"total": total, "sent": sent, "failed": failed, "errors": errors})


# ─── Settings ───

async def handle_settings(request):
    return _json({
        "FREE_ANSWERS_LIMIT": FREE_ANSWERS_LIMIT,
        "WARNING_AT": WARNING_AT,
        "RATE_LIMIT_PER_MINUTE": RATE_LIMIT_PER_MINUTE,
        "USTAZ_MONTHLY_LIMIT": USTAZ_MONTHLY_LIMIT,
        "CONVERSATION_HISTORY_LIMIT": CONVERSATION_HISTORY_LIMIT,
        "OPENAI_MODEL": OPENAI_MODEL,
        "DATABASE_PATH": DATABASE_PATH,
        "CACHE_THRESHOLD": CACHE_THRESHOLD,
        "SUBSCRIPTION_PLANS": SUBSCRIPTION_PLANS,
        "DOMAIN": DOMAIN,
        "KASPI_PAY_LINK": KASPI_PAY_LINK or "-",
        "KASPI_PRICE_KZT": KASPI_PRICE_KZT,
        "KASPI_PLAN_DAYS": KASPI_PLAN_DAYS,
    })


# ══════════════════════════════════════════════════════════════════
#  Секция 4: HTML SPA
# ══════════════════════════════════════════════════════════════════

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ramadan Bot Admin</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  background:#0a0f18;color:#e4e6eb;min-height:100vh;display:flex;flex-direction:column}
a{color:#3390ec;text-decoration:none}

/* Header */
.header{background:#111927;padding:12px 24px;display:flex;align-items:center;
  justify-content:space-between;border-bottom:1px solid #1e2d3d;position:sticky;top:0;z-index:100}
.header h1{font-size:18px;font-weight:600;color:#e4e6eb}
.header .user-info{font-size:13px;color:#8899a6}

/* Layout */
.layout{display:flex;flex:1;overflow:hidden}

/* Sidebar */
.sidebar{width:200px;background:#111927;border-right:1px solid #1e2d3d;
  padding:12px 0;flex-shrink:0;overflow-y:auto;height:calc(100vh - 49px)}
.sidebar .nav-item{display:flex;align-items:center;padding:10px 20px;
  cursor:pointer;color:#8899a6;font-size:14px;transition:all .15s}
.sidebar .nav-item:hover{background:#1a2332;color:#e4e6eb}
.sidebar .nav-item.active{background:#1a2332;color:#3390ec;border-right:3px solid #3390ec}
.sidebar .nav-item svg{width:18px;height:18px;margin-right:10px;flex-shrink:0}

/* Main */
.main{flex:1;overflow-y:auto;padding:24px;height:calc(100vh - 49px)}

/* Cards */
.stat-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:24px}
.stat-card{background:#17212b;border-radius:12px;padding:20px;border:1px solid #1e2d3d}
.stat-card .label{font-size:13px;color:#8899a6;margin-bottom:8px}
.stat-card .value{font-size:28px;font-weight:700;color:#e4e6eb}
.stat-card .value.blue{color:#3390ec}
.stat-card .value.green{color:#52b788}
.stat-card .value.orange{color:#fb8c00}

/* Section card */
.section{background:#17212b;border-radius:12px;border:1px solid #1e2d3d;padding:20px;margin-bottom:20px}
.section h2{font-size:16px;font-weight:600;margin-bottom:16px;color:#e4e6eb}
.section h3{font-size:14px;font-weight:600;margin-bottom:12px;color:#8899a6}

/* Tables */
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:10px 12px;color:#8899a6;border-bottom:1px solid #1e2d3d;
  font-weight:500;white-space:nowrap}
td{padding:10px 12px;border-bottom:1px solid #1e2d3d1a;color:#e4e6eb;vertical-align:top}
tr:hover td{background:#1a2332}

/* Badges */
.badge{display:inline-block;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600}
.badge-pending{background:#fb8c0033;color:#fb8c00}
.badge-answered{background:#52b78833;color:#52b788}
.badge-active{background:#3390ec33;color:#3390ec}
.badge-progress{background:#a78bfa33;color:#a78bfa}
.badge-inactive{background:#f8717133;color:#f87171}
.badge-free{background:#8899a633;color:#8899a6}
.badge-yes{background:#52b78833;color:#52b788}
.badge-no{background:#f8717133;color:#f87171}
.badge-auto_approved{background:#a78bfa33;color:#a78bfa}
.badge-approved{background:#52b78833;color:#52b788}
.badge-rejected{background:#f8717133;color:#f87171}

/* Buttons */
.btn{display:inline-flex;align-items:center;padding:6px 14px;border-radius:8px;
  border:none;cursor:pointer;font-size:12px;font-weight:600;transition:all .15s}
.btn-primary{background:#3390ec;color:#fff}
.btn-primary:hover{background:#2b7dd4}
.btn-danger{background:#f87171;color:#fff}
.btn-danger:hover{background:#dc2626}
.btn-success{background:#52b788;color:#fff}
.btn-success:hover{background:#3d9970}
.btn-sm{padding:4px 10px;font-size:11px}

/* Inputs */
input[type="text"],input[type="number"],select,textarea{
  background:#0a0f18;border:1px solid #1e2d3d;color:#e4e6eb;padding:8px 12px;
  border-radius:8px;font-size:13px;outline:none;transition:border .15s}
input:focus,select:focus,textarea:focus{border-color:#3390ec}
textarea{resize:vertical;min-height:80px;width:100%;font-family:inherit}

/* Toolbar */
.toolbar{display:flex;gap:10px;margin-bottom:16px;flex-wrap:wrap;align-items:center}
.toolbar input[type="text"]{width:260px}
.toolbar select{min-width:140px}

/* Pagination */
.pagination{display:flex;gap:6px;margin-top:16px;align-items:center;justify-content:center}
.pagination .pg-btn{padding:6px 12px;border-radius:6px;border:1px solid #1e2d3d;
  background:#17212b;color:#8899a6;cursor:pointer;font-size:12px}
.pagination .pg-btn:hover{background:#1a2332;color:#e4e6eb}
.pagination .pg-btn.active{background:#3390ec;color:#fff;border-color:#3390ec}
.pagination .pg-info{font-size:12px;color:#8899a6;padding:6px 8px}

/* Detail panel */
.detail-row{padding:12px 0;border-bottom:1px solid #1e2d3d1a}
.detail-row:last-child{border-bottom:none}
.detail-label{font-size:12px;color:#8899a6;margin-bottom:4px}
.detail-value{font-size:14px;color:#e4e6eb;word-break:break-all}

/* Expand row */
.expand-content{display:none;padding:12px;background:#0a0f18;border-radius:8px;margin-top:8px}
.expand-content.show{display:block}

/* Toast */
.toast-container{position:fixed;bottom:24px;right:24px;z-index:9999;display:flex;flex-direction:column;gap:8px}
.toast{padding:12px 20px;border-radius:8px;font-size:13px;font-weight:500;
  animation:slideIn .3s ease;max-width:360px;word-break:break-word}
.toast-success{background:#52b788;color:#fff}
.toast-error{background:#f87171;color:#fff}
.toast-info{background:#3390ec;color:#fff}
@keyframes slideIn{from{opacity:0;transform:translateX(40px)}to{opacity:1;transform:translateX(0)}}

/* Form group */
.form-group{margin-bottom:12px}
.form-group label{display:block;font-size:12px;color:#8899a6;margin-bottom:4px}

/* Tabs */
.tabs{display:flex;gap:0;margin-bottom:16px;border-bottom:1px solid #1e2d3d}
.tab{padding:10px 20px;cursor:pointer;font-size:13px;color:#8899a6;
  border-bottom:2px solid transparent;transition:all .15s}
.tab:hover{color:#e4e6eb}
.tab.active{color:#3390ec;border-bottom-color:#3390ec}

/* Truncate */
.truncate{max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:block}

/* Settings list */
.settings-list{list-style:none}
.settings-list li{padding:12px 0;border-bottom:1px solid #1e2d3d1a;display:flex;justify-content:space-between}
.settings-list .s-key{color:#8899a6;font-size:13px}
.settings-list .s-val{color:#e4e6eb;font-size:13px;font-weight:600;text-align:right;max-width:50%;word-break:break-all}

/* Modal */
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:200;
  align-items:center;justify-content:center}
.modal-overlay.show{display:flex}
.modal{background:#17212b;border:1px solid #1e2d3d;border-radius:12px;padding:24px;
  width:90%;max-width:480px;max-height:80vh;overflow-y:auto}
.modal.modal-lg{max-width:720px}
.modal h3{margin-bottom:16px;font-size:16px}
.modal-actions{display:flex;gap:10px;margin-top:16px;justify-content:flex-end}

/* Responsive */
@media(max-width:768px){
  .sidebar{width:56px}
  .sidebar .nav-item span{display:none}
  .sidebar .nav-item{justify-content:center;padding:12px}
  .sidebar .nav-item svg{margin:0}
  .main{padding:16px}
  .stat-cards{grid-template-columns:1fr 1fr}
  .toolbar input[type="text"]{width:100%}
}
</style>
</head>
<body>

<div class="header">
  <h1>Ramadan Bot Admin</h1>
  <div class="user-info">admin</div>
</div>

<div class="layout">
  <div class="sidebar" id="sidebar">
    <div class="nav-item active" onclick="navigate('dashboard')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
      <span>Dashboard</span>
    </div>
    <div class="nav-item" onclick="navigate('users')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/></svg>
      <span>Users</span>
    </div>
    <div class="nav-item" onclick="navigate('consultations')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
      <span>Consultations</span>
    </div>
    <div class="nav-item" onclick="navigate('ustazs')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 14l9-5-9-5-9 5 9 5z"/><path d="M12 14l6.16-3.42A12.08 12.08 0 0121 17.5c0 1.1-4.03 2.5-9 2.5s-9-1.4-9-2.5c0-2.52 1.05-4.8 2.84-6.42L12 14z"/></svg>
      <span>Ustazs</span>
    </div>
    <div class="nav-item" onclick="navigate('tickets')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.5 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V7.5L14.5 2z"/><polyline points="14,2 14,8 20,8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
      <span>Tickets</span>
    </div>
    <div class="nav-item" onclick="navigate('kaspi')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="1" y="4" width="22" height="16" rx="2" ry="2"/><line x1="1" y1="10" x2="23" y2="10"/></svg>
      <span>Kaspi</span>
    </div>
    <div class="nav-item" onclick="navigate('logs')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22,12 18,12 15,21 9,3 6,12 2,12"/></svg>
      <span>Logs</span>
    </div>
    <div class="nav-item" onclick="navigate('broadcast')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 11l18-5v12L3 13v-2z"/><path d="M11.6 16.8a3 3 0 11-5.8-1.6"/></svg>
      <span>Broadcast</span>
    </div>
    <div class="nav-item" onclick="navigate('settings')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>
      <span>Settings</span>
    </div>
  </div>

  <div class="main" id="main"></div>
</div>

<div class="toast-container" id="toasts"></div>

<!-- Modal for grant subscription -->
<div class="modal-overlay" id="modal-overlay" onclick="if(event.target===this)closeModal()">
  <div class="modal" id="modal-content"></div>
</div>

<script>
// ─── State ───
let currentPage = 'dashboard';
let debounceTimer = null;

// ─── API helpers ───
async function apiGet(path) {
  const r = await fetch(path);
  if (!r.ok) { const e = await r.json().catch(()=>({})); throw new Error(e.error || r.statusText); }
  return r.json();
}
async function apiPost(path, body) {
  const r = await fetch(path, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if (!r.ok) { const e = await r.json().catch(()=>({})); throw new Error(e.error || r.statusText); }
  return r.json();
}

// ─── Toast ───
function toast(msg, type='info') {
  const c = document.getElementById('toasts');
  const t = document.createElement('div');
  t.className = 'toast toast-' + type;
  t.textContent = msg;
  c.appendChild(t);
  setTimeout(() => t.remove(), 4000);
}

// ─── Modal ───
function openModal(html, cls) {
  const mc = document.getElementById('modal-content');
  mc.innerHTML = html;
  mc.className = 'modal' + (cls ? ' ' + cls : '');
  document.getElementById('modal-overlay').classList.add('show');
}
function closeModal() {
  document.getElementById('modal-overlay').classList.remove('show');
}

// ─── Pagination ───
function paginationHTML(total, page, perPage, onClickFn) {
  const pages = Math.ceil(total / perPage);
  if (pages <= 1) return '';
  let h = '<div class="pagination">';
  if (page > 1) h += `<div class="pg-btn" onclick="${onClickFn}(${page-1})">&laquo;</div>`;
  const start = Math.max(1, page - 3);
  const end = Math.min(pages, page + 3);
  for (let i = start; i <= end; i++) {
    h += `<div class="pg-btn${i===page?' active':''}" onclick="${onClickFn}(${i})">${i}</div>`;
  }
  if (page < pages) h += `<div class="pg-btn" onclick="${onClickFn}(${page+1})">&raquo;</div>`;
  h += `<div class="pg-info">${total} total</div></div>`;
  return h;
}

// ─── Navigation ───
function navigate(page) {
  currentPage = page;
  document.querySelectorAll('.nav-item').forEach((el, i) => {
    const pages = ['dashboard','users','consultations','ustazs','tickets','kaspi','logs','broadcast','settings'];
    el.classList.toggle('active', pages[i] === page);
  });
  renderPage();
}

function renderPage() {
  const m = document.getElementById('main');
  m.innerHTML = '<div style="text-align:center;padding:40px;color:#8899a6">Loading...</div>';
  switch(currentPage) {
    case 'dashboard': renderDashboard(); break;
    case 'users': renderUsers(1); break;
    case 'consultations': renderConsultations(1); break;
    case 'ustazs': renderUstazs(); break;
    case 'tickets': renderTickets(1); break;
    case 'kaspi': renderKaspi(1); break;
    case 'logs': renderLogs(1); break;
    case 'broadcast': renderBroadcast(); break;
    case 'settings': renderSettings(); break;
  }
}

// ─── Helpers ───
function esc(s) { if(!s) return ''; return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function badgeFor(status) {
  const map = {pending:'badge-pending',answered:'badge-answered',active:'badge-active',
    in_progress:'badge-progress',inactive:'badge-inactive'};
  return `<span class="badge ${map[status]||'badge-free'}">${esc(status)}</span>`;
}
function fmtDate(d) { if(!d) return '-'; return String(d).replace('T',' ').substring(0,19); }
function userName(item, prefix) {
  prefix = prefix || '';
  const fn = item[prefix+'first_name'] || '';
  const un = item[prefix+'username'] ? ('@'+item[prefix+'username']) : '';
  return esc(fn || un || '-');
}

// ══════════════════════════════════════════════
//  RENDER FUNCTIONS
// ══════════════════════════════════════════════

// ─── Dashboard ───
async function renderDashboard() {
  try {
    const d = await apiGet('/api/admin/dashboard');
    const cs = d.consultation_stats || {};
    const ts = d.ticket_stats || {};
    document.getElementById('main').innerHTML = `
      <div class="stat-cards">
        <div class="stat-card"><div class="label">Total Users</div><div class="value blue">${d.total_users}</div></div>
        <div class="stat-card"><div class="label">Total Queries</div><div class="value">${d.total_queries}</div></div>
        <div class="stat-card"><div class="label">Answered %</div><div class="value green">${d.answered_pct}%</div></div>
        <div class="stat-card"><div class="label">Subscribed</div><div class="value orange">${d.subscribed_users}</div></div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
        <div class="section">
          <h2>Consultations</h2>
          <div class="stat-cards" style="margin-bottom:0">
            <div class="stat-card"><div class="label">Pending</div><div class="value orange">${cs.pending||0}</div></div>
            <div class="stat-card"><div class="label">In Progress</div><div class="value blue">${cs.in_progress||0}</div></div>
            <div class="stat-card"><div class="label">Answered</div><div class="value green">${cs.answered||0}</div></div>
            <div class="stat-card"><div class="label">Total</div><div class="value">${cs.total||0}</div></div>
          </div>
        </div>
        <div class="section">
          <h2>Tickets</h2>
          <div class="stat-cards" style="margin-bottom:0">
            <div class="stat-card"><div class="label">Pending</div><div class="value orange">${ts.pending||0}</div></div>
            <div class="stat-card"><div class="label">Answered</div><div class="value green">${ts.answered||0}</div></div>
            <div class="stat-card"><div class="label">Total</div><div class="value">${ts.total||0}</div></div>
          </div>
        </div>
      </div>`;
  } catch(e) { toast(e.message, 'error'); }
}

// ─── Users ───
let usersSearch = '';
let usersFilter = 'all';

async function renderUsers(page) {
  try {
    const d = await apiGet(`/api/admin/users?page=${page}&search=${encodeURIComponent(usersSearch)}&filter=${usersFilter}`);
    let h = `
      <div class="section">
        <h2>Users</h2>
        <div class="toolbar">
          <input type="text" id="userSearch" placeholder="Search by name, username, ID..." value="${esc(usersSearch)}"
            oninput="clearTimeout(debounceTimer);debounceTimer=setTimeout(()=>{usersSearch=this.value;renderUsers(1)},400)">
          <select id="userFilter" onchange="usersFilter=this.value;renderUsers(1)">
            <option value="all"${usersFilter==='all'?' selected':''}>All</option>
            <option value="subscribed"${usersFilter==='subscribed'?' selected':''}>Subscribed</option>
            <option value="free"${usersFilter==='free'?' selected':''}>Free</option>
          </select>
        </div>
        <table>
          <tr><th>ID</th><th>Telegram</th><th>Name</th><th>Queries</th><th>Subscribed</th><th>City</th><th>Lang</th><th>Joined</th><th>Actions</th></tr>`;
    for (const u of d.items) {
      const sub = u.is_subscribed
        ? `<span class="badge badge-yes">Yes</span>`
        : `<span class="badge badge-no">No</span>`;
      h += `<tr>
        <td>${u.telegram_id}</td>
        <td>${esc(u.username ? '@'+u.username : '-')}</td>
        <td>${esc(u.first_name||'-')}</td>
        <td>${u.answers_count}</td>
        <td>${sub}</td>
        <td>${esc(u.city||'-')}</td>
        <td>${esc(u.language||'-')}</td>
        <td>${fmtDate(u.created_at)}</td>
        <td>
          <button class="btn btn-primary btn-sm" onclick="showUserDetail(${u.telegram_id})">View</button>
          ${u.is_subscribed
            ? `<button class="btn btn-danger btn-sm" onclick="revokeUser(${u.telegram_id})">Revoke</button>`
            : `<button class="btn btn-success btn-sm" onclick="showGrantModal(${u.telegram_id})">Grant</button>`
          }
        </td>
      </tr>`;
    }
    h += `</table>${paginationHTML(d.total, d.page, d.per_page, 'renderUsers')}</div>`;
    document.getElementById('main').innerHTML = h;
  } catch(e) { toast(e.message, 'error'); }
}

async function showUserDetail(tid) {
  try {
    const u = await apiGet(`/api/admin/users/${tid}`);
    let subH = '';
    if (u.subscriptions && u.subscriptions.length) {
      subH = '<h3>Subscription History</h3><table><tr><th>Plan</th><th>Amount</th><th>Started</th><th>Expires</th></tr>';
      for (const s of u.subscriptions) {
        subH += `<tr><td>${esc(s.plan_name)}</td><td>${s.amount} ${esc(s.currency)}</td><td>${fmtDate(s.started_at)}</td><td>${fmtDate(s.expires_at)}</td></tr>`;
      }
      subH += '</table>';
    }
    let logsH = '';
    if (u.logs && u.logs.length) {
      logsH = '<h3 style="margin-top:16px">Recent Queries</h3><table><tr><th>Query</th><th>Answered</th><th>Score</th><th>Date</th></tr>';
      for (const l of u.logs) {
        logsH += `<tr><td><span class="truncate">${esc(l.query_text)}</span></td><td>${l.was_answered?'Yes':'No'}</td>
          <td>${l.similarity_score?l.similarity_score.toFixed(2):'-'}</td><td>${fmtDate(l.created_at)}</td></tr>`;
      }
      logsH += '</table>';
    }
    let consH = '';
    if (u.consultations && u.consultations.length) {
      consH = '<h3 style="margin-top:16px">Consultations</h3><table><tr><th>ID</th><th>Status</th><th>Question</th><th>Date</th></tr>';
      for (const c of u.consultations) {
        consH += `<tr><td>${c.id}</td><td>${badgeFor(c.status)}</td><td><span class="truncate">${esc(c.question_text)}</span></td><td>${fmtDate(c.created_at)}</td></tr>`;
      }
      consH += '</table>';
    }
    openModal(`
      <h3>User: ${esc(u.first_name||'')} ${esc(u.username?'(@'+u.username+')':'')}</h3>
      <div class="detail-row"><div class="detail-label">Telegram ID</div><div class="detail-value">${u.telegram_id}</div></div>
      <div class="detail-row"><div class="detail-label">Answers Used</div><div class="detail-value">${u.answers_count}</div></div>
      <div class="detail-row"><div class="detail-label">Subscribed</div><div class="detail-value">${u.is_subscribed?'Yes':'No'}${u.subscription_expires_at?' (until '+fmtDate(u.subscription_expires_at)+')':''}</div></div>
      <div class="detail-row"><div class="detail-label">City</div><div class="detail-value">${esc(u.city||'-')}</div></div>
      <div class="detail-row"><div class="detail-label">Language</div><div class="detail-value">${esc(u.language||'-')}</div></div>
      <div class="detail-row"><div class="detail-label">Onboarded</div><div class="detail-value">${u.is_onboarded?'Yes':'No'}</div></div>
      <div class="detail-row"><div class="detail-label">Joined</div><div class="detail-value">${fmtDate(u.created_at)}</div></div>
      ${subH}${consH}${logsH}
      <div class="modal-actions"><button class="btn btn-primary" onclick="closeModal()">Close</button></div>
    `);
  } catch(e) { toast(e.message,'error'); }
}

function showGrantModal(tid) {
  openModal(`
    <h3>Grant Subscription</h3>
    <div class="form-group"><label>Plan</label>
      <select id="grantPlan"><option value="manual">Manual</option><option value="monthly">Monthly (30d)</option><option value="yearly">Yearly (365d)</option></select>
    </div>
    <div class="form-group"><label>Days</label>
      <input type="number" id="grantDays" value="30" min="1" max="3650">
    </div>
    <div class="modal-actions">
      <button class="btn btn-primary" onclick="doGrant(${tid})">Grant</button>
      <button class="btn btn-danger" onclick="closeModal()">Cancel</button>
    </div>
  `);
  document.getElementById('grantPlan').addEventListener('change', function() {
    if (this.value === 'monthly') document.getElementById('grantDays').value = 30;
    if (this.value === 'yearly') document.getElementById('grantDays').value = 365;
  });
}

async function doGrant(tid) {
  try {
    const plan = document.getElementById('grantPlan').value;
    const days = parseInt(document.getElementById('grantDays').value);
    await apiPost(`/api/admin/users/${tid}/grant`, {plan, days});
    toast('Subscription granted!', 'success');
    closeModal();
    renderUsers(1);
  } catch(e) { toast(e.message,'error'); }
}

async function revokeUser(tid) {
  if (!confirm('Revoke subscription for user ' + tid + '?')) return;
  try {
    await apiPost(`/api/admin/users/${tid}/revoke`, {});
    toast('Subscription revoked', 'success');
    renderUsers(1);
  } catch(e) { toast(e.message,'error'); }
}

// ─── Consultations ───
let consFilter = 'all';

async function renderConsultations(page) {
  try {
    const d = await apiGet(`/api/admin/consultations?page=${page}&status=${consFilter}`);
    let h = `
      <div class="section">
        <h2>Consultations</h2>
        <div class="toolbar">
          <select onchange="consFilter=this.value;renderConsultations(1)">
            <option value="all"${consFilter==='all'?' selected':''}>All</option>
            <option value="pending"${consFilter==='pending'?' selected':''}>Pending</option>
            <option value="in_progress"${consFilter==='in_progress'?' selected':''}>In Progress</option>
            <option value="answered"${consFilter==='answered'?' selected':''}>Answered</option>
          </select>
        </div>
        <table>
          <tr><th>ID</th><th>User</th><th>Ustaz</th><th>Status</th><th>Question</th><th>Created</th><th></th></tr>`;
    for (const c of d.items) {
      h += `<tr>
        <td>${c.id}</td>
        <td>${userName(c,'user_')}</td>
        <td>${c.ustaz_telegram_id ? userName(c,'ustaz_') : '-'}</td>
        <td>${badgeFor(c.status)}</td>
        <td><span class="truncate">${esc(c.question_text)}</span></td>
        <td>${fmtDate(c.created_at)}</td>
        <td><button class="btn btn-primary btn-sm" onclick="showConsultation(${c.id})">View</button></td>
      </tr>`;
    }
    h += `</table>${paginationHTML(d.total, d.page, d.per_page, 'renderConsultations')}</div>`;
    document.getElementById('main').innerHTML = h;
  } catch(e) { toast(e.message,'error'); }
}

async function showConsultation(id) {
  try {
    const c = await apiGet(`/api/admin/consultations/${id}`);
    openModal(`
      <h3>Consultation #${c.id}</h3>
      <div class="detail-row"><div class="detail-label">Status</div><div class="detail-value">${badgeFor(c.status)}</div></div>
      <div class="detail-row"><div class="detail-label">User</div><div class="detail-value">${c.user_telegram_id}</div></div>
      <div class="detail-row"><div class="detail-label">Ustaz</div><div class="detail-value">${c.ustaz_telegram_id||'-'}</div></div>
      <div class="detail-row"><div class="detail-label">Question</div><div class="detail-value">${esc(c.question_text)}</div></div>
      <div class="detail-row"><div class="detail-label">AI Answer</div><div class="detail-value">${esc(c.ai_answer_text||'-')}</div></div>
      <div class="detail-row"><div class="detail-label">Ustaz Answer</div><div class="detail-value">${esc(c.answer_text||'-')}</div></div>
      <div class="detail-row"><div class="detail-label">Created</div><div class="detail-value">${fmtDate(c.created_at)}</div></div>
      <div class="detail-row"><div class="detail-label">Answered</div><div class="detail-value">${fmtDate(c.answered_at)}</div></div>
      <div class="modal-actions"><button class="btn btn-primary" onclick="closeModal()">Close</button></div>
    `);
  } catch(e) { toast(e.message,'error'); }
}

// ─── Ustazs ───
async function renderUstazs() {
  try {
    const d = await apiGet('/api/admin/ustazs');
    let h = `
      <div class="section">
        <h2>Ustazs</h2>
        <div style="background:#0a0f18;border-radius:8px;padding:16px;margin-bottom:16px">
          <h3 style="margin-bottom:12px">Add Ustaz</h3>
          <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end">
            <div class="form-group" style="margin-bottom:0"><label>Telegram ID</label><input type="number" id="newUstazId" placeholder="123456789"></div>
            <div class="form-group" style="margin-bottom:0"><label>Username</label><input type="text" id="newUstazUsername" placeholder="username"></div>
            <div class="form-group" style="margin-bottom:0"><label>Name</label><input type="text" id="newUstazName" placeholder="First name"></div>
            <button class="btn btn-success" onclick="addUstaz()">Add</button>
          </div>
        </div>
        <table>
          <tr><th>ID</th><th>Telegram</th><th>Username</th><th>Name</th><th>Active</th><th>Answered</th><th>Joined</th><th>Actions</th></tr>`;
    for (const u of d.items) {
      h += `<tr>
        <td>${u.id}</td>
        <td>${u.telegram_id}</td>
        <td>${esc(u.username ? '@'+u.username : '-')}</td>
        <td>${esc(u.first_name||'-')}</td>
        <td>${u.is_active ? '<span class="badge badge-active">Active</span>' : '<span class="badge badge-inactive">Inactive</span>'}</td>
        <td>${u.total_answered}</td>
        <td>${fmtDate(u.created_at)}</td>
        <td>
          ${u.is_active
            ? `<button class="btn btn-danger btn-sm" onclick="deactivateUstaz(${u.telegram_id})">Deactivate</button>`
            : `<button class="btn btn-success btn-sm" onclick="activateUstaz(${u.telegram_id})">Activate</button>`
          }
        </td>
      </tr>`;
    }
    h += '</table></div>';
    document.getElementById('main').innerHTML = h;
  } catch(e) { toast(e.message,'error'); }
}

async function addUstaz() {
  const tid = document.getElementById('newUstazId').value;
  const uname = document.getElementById('newUstazUsername').value;
  const fname = document.getElementById('newUstazName').value;
  if (!tid) { toast('Telegram ID is required','error'); return; }
  try {
    await apiPost('/api/admin/ustazs', {telegram_id: parseInt(tid), username: uname, first_name: fname});
    toast('Ustaz added!','success');
    renderUstazs();
  } catch(e) { toast(e.message,'error'); }
}

async function deactivateUstaz(tid) {
  if (!confirm('Deactivate ustaz ' + tid + '?')) return;
  try {
    await apiPost(`/api/admin/ustazs/${tid}/deactivate`, {});
    toast('Ustaz deactivated','success');
    renderUstazs();
  } catch(e) { toast(e.message,'error'); }
}

async function activateUstaz(tid) {
  try {
    await apiPost(`/api/admin/ustazs/${tid}/activate`, {});
    toast('Ustaz activated','success');
    renderUstazs();
  } catch(e) { toast(e.message,'error'); }
}

// ─── Tickets ───
let ticketFilter = 'all';

async function renderTickets(page) {
  try {
    const d = await apiGet(`/api/admin/tickets?page=${page}&status=${ticketFilter}`);
    let h = `
      <div class="section">
        <h2>Tickets</h2>
        <div class="toolbar">
          <select onchange="ticketFilter=this.value;renderTickets(1)">
            <option value="all"${ticketFilter==='all'?' selected':''}>All</option>
            <option value="pending"${ticketFilter==='pending'?' selected':''}>Pending</option>
            <option value="answered"${ticketFilter==='answered'?' selected':''}>Answered</option>
          </select>
        </div>
        <table>
          <tr><th>ID</th><th>User</th><th>Status</th><th>Message</th><th>Response</th><th>Created</th><th></th></tr>`;
    for (const t of d.items) {
      const actions = t.status === 'pending'
        ? `<button class="btn btn-success btn-sm" onclick="showTicketAnswer(${t.id})">Answer</button>`
        : `<button class="btn btn-primary btn-sm" onclick="showTicketDetail(${t.id})">View</button>`;
      h += `<tr>
        <td>${t.id}</td>
        <td>${userName(t,'')}</td>
        <td>${badgeFor(t.status)}</td>
        <td><span class="truncate">${esc(t.message_text)}</span></td>
        <td><span class="truncate">${esc(t.moderator_response||'-')}</span></td>
        <td>${fmtDate(t.created_at)}</td>
        <td>${actions}</td>
      </tr>`;
    }
    h += `</table>${paginationHTML(d.total, d.page, d.per_page, 'renderTickets')}</div>`;
    document.getElementById('main').innerHTML = h;
  } catch(e) { toast(e.message,'error'); }
}

async function showTicketDetail(id) {
  try {
    const t = await apiGet(`/api/admin/tickets/${id}`);
    openModal(`
      <h3>Ticket #${t.id}</h3>
      <div class="detail-row"><div class="detail-label">Status</div><div class="detail-value">${badgeFor(t.status)}</div></div>
      <div class="detail-row"><div class="detail-label">User</div><div class="detail-value">${t.user_telegram_id} ${esc(t.first_name||'')} ${esc(t.username?'(@'+t.username+')':'')}</div></div>
      <div class="detail-row"><div class="detail-label">Message</div><div class="detail-value">${esc(t.message_text)}</div></div>
      <div class="detail-row"><div class="detail-label">Response</div><div class="detail-value">${esc(t.moderator_response||'-')}</div></div>
      <div class="detail-row"><div class="detail-label">Created</div><div class="detail-value">${fmtDate(t.created_at)}</div></div>
      <div class="detail-row"><div class="detail-label">Responded</div><div class="detail-value">${fmtDate(t.responded_at)}</div></div>
      <div class="modal-actions"><button class="btn btn-primary" onclick="closeModal()">Close</button></div>
    `);
  } catch(e) { toast(e.message,'error'); }
}

async function showTicketAnswer(id) {
  try {
    const t = await apiGet(`/api/admin/tickets/${id}`);
    openModal(`
      <h3>Answer Ticket #${t.id}</h3>
      <div class="detail-row"><div class="detail-label">User</div><div class="detail-value">${t.user_telegram_id} ${esc(t.first_name||'')} ${esc(t.username?'(@'+t.username+')':'')}</div></div>
      <div class="detail-row"><div class="detail-label">Message</div><div class="detail-value">${esc(t.message_text)}</div></div>
      <div class="form-group" style="margin-top:12px"><label>Your Response</label>
        <textarea id="ticketResponse" rows="4" placeholder="Write your response..."></textarea>
      </div>
      <div class="modal-actions">
        <button class="btn btn-success" onclick="doAnswerTicket(${t.id})">Send Answer</button>
        <button class="btn btn-danger" onclick="closeModal()">Cancel</button>
      </div>
    `);
  } catch(e) { toast(e.message,'error'); }
}

async function doAnswerTicket(id) {
  const response = document.getElementById('ticketResponse').value;
  if (!response.trim()) { toast('Response cannot be empty','error'); return; }
  try {
    await apiPost(`/api/admin/tickets/${id}/answer`, {response});
    toast('Ticket answered!','success');
    closeModal();
    renderTickets(1);
  } catch(e) { toast(e.message,'error'); }
}

// ─── Logs ───
let logsFilter = 'all';
let logsTab = 'recent';

async function renderLogs(page) {
  let tabsH = `
    <div class="tabs">
      <div class="tab${logsTab==='recent'?' active':''}" onclick="logsTab='recent';renderLogs(1)">Recent Queries</div>
      <div class="tab${logsTab==='unanswered'?' active':''}" onclick="logsTab='unanswered';renderLogsUnanswered()">Top Unanswered</div>
      <div class="tab${logsTab==='popular'?' active':''}" onclick="logsTab='popular';renderLogsPopular()">Top Popular</div>
    </div>`;

  if (logsTab !== 'recent') {
    if (logsTab === 'unanswered') { renderLogsUnanswered(); return; }
    if (logsTab === 'popular') { renderLogsPopular(); return; }
  }

  try {
    const d = await apiGet(`/api/admin/logs?page=${page}&filter=${logsFilter}`);
    let h = `<div class="section"><h2>Logs</h2>${tabsH}
      <div class="toolbar">
        <select onchange="logsFilter=this.value;renderLogs(1)">
          <option value="all"${logsFilter==='all'?' selected':''}>All</option>
          <option value="answered"${logsFilter==='answered'?' selected':''}>Answered</option>
          <option value="unanswered"${logsFilter==='unanswered'?' selected':''}>Unanswered</option>
        </select>
      </div>
      <table>
        <tr><th>ID</th><th>User</th><th>Query</th><th>Matched</th><th>Score</th><th>Answered</th><th>Date</th></tr>`;
    for (const l of d.items) {
      h += `<tr>
        <td>${l.id}</td>
        <td>${userName(l,'')}</td>
        <td><span class="truncate">${esc(l.query_text)}</span></td>
        <td><span class="truncate">${esc(l.matched_question||'-')}</span></td>
        <td>${l.similarity_score ? Number(l.similarity_score).toFixed(2) : '-'}</td>
        <td>${l.was_answered ? '<span class="badge badge-yes">Yes</span>' : '<span class="badge badge-no">No</span>'}</td>
        <td>${fmtDate(l.created_at)}</td>
      </tr>`;
    }
    h += `</table>${paginationHTML(d.total, d.page, d.per_page, 'renderLogs')}</div>`;
    document.getElementById('main').innerHTML = h;
  } catch(e) { toast(e.message,'error'); }
}

async function renderLogsUnanswered() {
  logsTab = 'unanswered';
  const tabsH = `
    <div class="tabs">
      <div class="tab" onclick="logsTab='recent';renderLogs(1)">Recent Queries</div>
      <div class="tab active" onclick="logsTab='unanswered';renderLogsUnanswered()">Top Unanswered</div>
      <div class="tab" onclick="logsTab='popular';renderLogsPopular()">Top Popular</div>
    </div>`;
  try {
    const d = await apiGet('/api/admin/logs/top-unanswered');
    let h = `<div class="section"><h2>Logs</h2>${tabsH}
      <table><tr><th>#</th><th>Question</th><th>Count</th></tr>`;
    d.items.forEach((item, i) => {
      h += `<tr><td>${i+1}</td><td>${esc(item.query_text)}</td><td><span class="badge badge-pending">${item.cnt}</span></td></tr>`;
    });
    if (!d.items.length) h += '<tr><td colspan="3" style="text-align:center;color:#8899a6">No unanswered questions</td></tr>';
    h += '</table></div>';
    document.getElementById('main').innerHTML = h;
  } catch(e) { toast(e.message,'error'); }
}

async function renderLogsPopular() {
  logsTab = 'popular';
  const tabsH = `
    <div class="tabs">
      <div class="tab" onclick="logsTab='recent';renderLogs(1)">Recent Queries</div>
      <div class="tab" onclick="logsTab='unanswered';renderLogsUnanswered()">Top Unanswered</div>
      <div class="tab active" onclick="logsTab='popular';renderLogsPopular()">Top Popular</div>
    </div>`;
  try {
    const d = await apiGet('/api/admin/logs/top-questions');
    let h = `<div class="section"><h2>Logs</h2>${tabsH}
      <table><tr><th>#</th><th>Matched Question</th><th>Count</th></tr>`;
    d.items.forEach((item, i) => {
      h += `<tr><td>${i+1}</td><td>${esc(item.matched_question)}</td><td><span class="badge badge-answered">${item.cnt}</span></td></tr>`;
    });
    if (!d.items.length) h += '<tr><td colspan="3" style="text-align:center;color:#8899a6">No data</td></tr>';
    h += '</table></div>';
    document.getElementById('main').innerHTML = h;
  } catch(e) { toast(e.message,'error'); }
}

// ─── Kaspi Payments ───
let kaspiFilter = 'all';

async function renderKaspi(page) {
  try {
    const d = await apiGet(`/api/admin/kaspi/list?page=${page}&status=${kaspiFilter}`);
    let h = `
      <div class="section">
        <h2>Kaspi Payments</h2>
        <div class="toolbar">
          <select onchange="kaspiFilter=this.value;renderKaspi(1)">
            <option value="all"${kaspiFilter==='all'?' selected':''}>All</option>
            <option value="pending"${kaspiFilter==='pending'?' selected':''}>Pending</option>
            <option value="auto_approved"${kaspiFilter==='auto_approved'?' selected':''}>Auto Approved</option>
            <option value="approved"${kaspiFilter==='approved'?' selected':''}>Approved</option>
            <option value="rejected"${kaspiFilter==='rejected'?' selected':''}>Rejected</option>
          </select>
        </div>
        <table>
          <tr><th>ID</th><th>User</th><th>Expected</th><th>Found</th><th>Receipt Date</th><th>Status</th><th>Created</th><th>Receipt</th><th>Actions</th></tr>`;
    for (const k of d.items) {
      const actions = (k.status === 'auto_approved' || k.status === 'pending')
        ? `<button class="btn btn-success btn-sm" onclick="approveKaspi(${k.id})">Approve</button>
           <button class="btn btn-danger btn-sm" onclick="rejectKaspi(${k.id})">Reject</button>`
        : badgeFor(k.status);
      const receiptBtn = k.receipt_file_id
        ? `<button class="btn btn-primary btn-sm" onclick="showReceipt(${k.id}, ${k.amount_expected}, '${esc(k.status)}', '${esc(k.created_at||'')}')">📷</button>`
        : '-';
      h += `<tr>
        <td>${k.id}</td>
        <td>${userName(k,'')}</td>
        <td>${k.amount_expected} ₸</td>
        <td>${k.amount_found != null ? k.amount_found + ' ₸' : '-'}</td>
        <td>${esc(k.comment_found||'-')}</td>
        <td>${badgeFor(k.status)}</td>
        <td>${fmtDate(k.created_at)}</td>
        <td>${receiptBtn}</td>
        <td>${actions}</td>
      </tr>`;
    }
    h += `</table>${paginationHTML(d.total, d.page, d.per_page, 'renderKaspi')}</div>`;
    document.getElementById('main').innerHTML = h;
  } catch(e) { toast(e.message,'error'); }
}

async function approveKaspi(id) {
  if (!confirm('Approve Kaspi payment #' + id + '?')) return;
  try {
    await apiPost(`/api/admin/kaspi/${id}/approve`, {});
    toast('Payment approved!','success');
    renderKaspi(1);
  } catch(e) { toast(e.message,'error'); }
}

async function rejectKaspi(id) {
  if (!confirm('Reject Kaspi payment #' + id + '? Subscription will be revoked.')) return;
  try {
    await apiPost(`/api/admin/kaspi/${id}/reject`, {});
    toast('Payment rejected, subscription revoked','success');
    renderKaspi(1);
  } catch(e) { toast(e.message,'error'); }
}

async function showReceipt(id, amount, status, createdAt) {
  openModal(`
    <h3>Receipt — Payment #${id}</h3>
    <div style="display:flex;gap:16px;margin-bottom:12px;flex-wrap:wrap">
      <div class="detail-row" style="flex:1;min-width:100px"><div class="detail-label">Amount</div><div class="detail-value">${amount} ₸</div></div>
      <div class="detail-row" style="flex:1;min-width:100px"><div class="detail-label">Status</div><div class="detail-value">${badgeFor(status)}</div></div>
      <div class="detail-row" style="flex:1;min-width:100px"><div class="detail-label">Created</div><div class="detail-value">${fmtDate(createdAt)}</div></div>
    </div>
    <div id="receipt-loader" style="text-align:center;padding:20px;color:#8899a6">Loading image...</div>
    <div class="modal-actions"><button class="btn btn-primary" onclick="closeModal()">Close</button></div>
  `, 'modal-lg');
  try {
    const r = await fetch(`/api/admin/kaspi/${id}/receipt`);
    if (!r.ok) throw new Error('Not found');
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const img = document.createElement('img');
    img.style.cssText = 'max-width:100%;border-radius:8px;border:1px solid #1e2d3d';
    img.src = url;
    document.getElementById('receipt-loader').replaceWith(img);
  } catch(e) {
    const el = document.getElementById('receipt-loader');
    if (el) el.innerHTML = '<span style="color:#f87171">Failed to load receipt image</span>';
  }
}

// ─── Broadcast ───
function renderBroadcast() {
  document.getElementById('main').innerHTML = `
    <div class="section">
      <h2>Broadcast Message</h2>
      <p style="color:#8899a6;font-size:13px;margin-bottom:16px">
        Send a message to all onboarded users. Supports HTML formatting.
      </p>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
        <div>
          <div class="form-group">
            <label>Message (HTML)</label>
            <textarea id="broadcastMsg" rows="12" placeholder="Enter message with HTML formatting..."
              oninput="updateBroadcastPreview()"></textarea>
          </div>
          <button class="btn btn-primary" onclick="doBroadcast()" id="broadcastBtn">Send to All Users</button>
        </div>
        <div>
          <div class="form-group"><label>Preview</label></div>
          <div id="broadcastPreview" style="background:#0a0f18;border:1px solid #1e2d3d;
            border-radius:8px;padding:16px;min-height:200px;font-size:14px;line-height:1.6;
            color:#e4e6eb;overflow-wrap:break-word"></div>
        </div>
      </div>
      <div id="broadcastResult" style="margin-top:20px"></div>
    </div>`;
}

function updateBroadcastPreview() {
  const msg = document.getElementById('broadcastMsg').value;
  document.getElementById('broadcastPreview').innerHTML = msg || '<span style="color:#8899a6">Preview will appear here...</span>';
}

async function doBroadcast() {
  const msg = document.getElementById('broadcastMsg').value.trim();
  if (!msg) { toast('Message cannot be empty','error'); return; }
  if (!confirm('Send this message to ALL users?')) return;

  const btn = document.getElementById('broadcastBtn');
  btn.disabled = true;
  btn.textContent = 'Sending...';

  try {
    const r = await apiPost('/api/admin/broadcast', {message: msg});
    let h = `<div class="stat-cards">
      <div class="stat-card"><div class="label">Total</div><div class="value">${r.total}</div></div>
      <div class="stat-card"><div class="label">Sent</div><div class="value green">${r.sent}</div></div>
      <div class="stat-card"><div class="label">Failed</div><div class="value orange">${r.failed}</div></div>
    </div>`;
    if (r.errors && r.errors.length) {
      h += '<div class="section" style="margin-top:12px"><h3>Errors</h3><table><tr><th>Telegram ID</th><th>Error</th></tr>';
      for (const e of r.errors) {
        h += '<tr><td>' + e.telegram_id + '</td><td>' + esc(e.error) + '</td></tr>';
      }
      h += '</table></div>';
    }
    document.getElementById('broadcastResult').innerHTML = h;
    toast('Broadcast complete: ' + r.sent + ' sent, ' + r.failed + ' failed', 'success');
  } catch(e) { toast(e.message,'error'); }
  finally {
    btn.disabled = false;
    btn.textContent = 'Send to All Users';
  }
}

// ─── Settings ───
async function renderSettings() {
  try {
    const s = await apiGet('/api/admin/settings');
    let h = '<div class="section"><h2>Settings (read-only)</h2><ul class="settings-list">';
    const display = [
      ['OPENAI_MODEL', s.OPENAI_MODEL],
      ['DATABASE_PATH', s.DATABASE_PATH],
      ['DOMAIN', s.DOMAIN || '-'],
      ['FREE_ANSWERS_LIMIT', s.FREE_ANSWERS_LIMIT],
      ['WARNING_AT', s.WARNING_AT],
      ['RATE_LIMIT_PER_MINUTE', s.RATE_LIMIT_PER_MINUTE],
      ['USTAZ_MONTHLY_LIMIT', s.USTAZ_MONTHLY_LIMIT],
      ['CONVERSATION_HISTORY_LIMIT', s.CONVERSATION_HISTORY_LIMIT],
      ['CACHE_THRESHOLD', s.CACHE_THRESHOLD],
      ['KASPI_PAY_LINK', s.KASPI_PAY_LINK || '-'],
      ['KASPI_PRICE_KZT', s.KASPI_PRICE_KZT],
      ['KASPI_PLAN_DAYS', s.KASPI_PLAN_DAYS],
    ];
    for (const [k, v] of display) {
      h += `<li><span class="s-key">${esc(k)}</span><span class="s-val">${esc(String(v))}</span></li>`;
    }
    // Plans
    h += '</ul><h3 style="margin-top:20px">Subscription Plans</h3><table><tr><th>Plan</th><th>Price</th><th>Currency</th><th>Days</th><th>Label</th></tr>';
    for (const [name, plan] of Object.entries(s.SUBSCRIPTION_PLANS||{})) {
      h += `<tr><td>${esc(name)}</td><td>${plan.price}</td><td>${esc(plan.currency)}</td><td>${plan.days}</td><td>${esc(plan.label)}</td></tr>`;
    }
    h += '</table></div>';
    document.getElementById('main').innerHTML = h;
  } catch(e) { toast(e.message,'error'); }
}

// ─── Init ───
navigate('dashboard');
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════
#  Секция 5: SPA endpoint + Auth + App init
# ══════════════════════════════════════════════════════════════════


async def handle_index(request):
    return web.Response(text=HTML_PAGE, content_type="text/html")


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
    """HTTP Basic Auth middleware."""
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
        headers={"WWW-Authenticate": 'Basic realm="Ramadan Bot Admin"'},
    )


async def init_app():
    if not WEB_ADMIN_PASSWORD:
        logger.error("WEB_ADMIN_PASSWORD is not set! Refusing to start without auth.")
        sys.exit(1)

    app = web.Application(middlewares=[security_headers_middleware, basic_auth_middleware])

    db = Database()
    await db.connect()
    app["db"] = db

    # Bot instance for broadcast
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    app["bot"] = bot

    async def cleanup_bot(app):
        await app["bot"].session.close()

    app.on_cleanup.append(cleanup_bot)

    # SPA
    app.router.add_get("/", handle_index)

    # Dashboard
    app.router.add_get("/api/admin/dashboard", handle_dashboard)

    # Users
    app.router.add_get("/api/admin/users", handle_users_list)
    app.router.add_get("/api/admin/users/{telegram_id}", handle_user_detail)
    app.router.add_post("/api/admin/users/{telegram_id}/grant", handle_user_grant)
    app.router.add_post("/api/admin/users/{telegram_id}/revoke", handle_user_revoke)

    # Consultations
    app.router.add_get("/api/admin/consultations", handle_consultations_list)
    app.router.add_get("/api/admin/consultations/{id}", handle_consultation_detail)

    # Ustazs
    app.router.add_get("/api/admin/ustazs", handle_ustazs_list)
    app.router.add_post("/api/admin/ustazs", handle_ustaz_add)
    app.router.add_post("/api/admin/ustazs/{id}/deactivate", handle_ustaz_deactivate)
    app.router.add_post("/api/admin/ustazs/{id}/activate", handle_ustaz_activate)

    # Tickets
    app.router.add_get("/api/admin/tickets", handle_tickets_list)
    app.router.add_get("/api/admin/tickets/{id}", handle_ticket_detail)
    app.router.add_post("/api/admin/tickets/{id}/answer", handle_ticket_answer)

    # Kaspi Payments
    app.router.add_get("/api/admin/kaspi/list", handle_kaspi_list)
    app.router.add_get("/api/admin/kaspi/{id}/receipt", handle_kaspi_receipt)
    app.router.add_post("/api/admin/kaspi/{id}/approve", handle_kaspi_approve)
    app.router.add_post("/api/admin/kaspi/{id}/reject", handle_kaspi_reject)

    # Logs
    app.router.add_get("/api/admin/logs", handle_logs_list)
    app.router.add_get("/api/admin/logs/top-unanswered", handle_logs_top_unanswered)
    app.router.add_get("/api/admin/logs/top-questions", handle_logs_top_questions)

    # Broadcast
    app.router.add_post("/api/admin/broadcast", handle_broadcast)

    # Settings
    app.router.add_get("/api/admin/settings", handle_settings)

    return app


def main():
    app = init_app()
    print(f"Starting Ramadan Bot Admin on port {ADMIN_PORT}...")
    web.run_app(app, host="0.0.0.0", port=ADMIN_PORT)


if __name__ == "__main__":
    main()
