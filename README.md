# Telegram Knowledge Bot — Рамазан / Ораза

Telegram-бот с базой знаний о Рамадане, оразе, зекете, садақа и других темах исламского поста. База знаний извлечена из 6 книг (PDF) на казахском языке — более 400 записей.

## Возможности

- Поиск ответов по смысловому сходству (embeddings) — 402 записи из 6 книг
- Понимает казахский и русский языки (кириллица + латиница)
- Устойчив к опечаткам
- Тематики: ораза, ниет, сәресі, ауызашар, тарауих, қадір түні, зекет, пітір, иғтикаф
- Система подписки (50 бесплатных ответов, далее — платная подписка)
- Админ-панель (статистика, управление подписками, перезагрузка базы)
- Скрипт извлечения Q&A из PDF-книг

## Установка

```bash
# 1. Клонировать репозиторий
git clone <repo-url>
cd telegram-knowledge-bot

# 2. Создать виртуальное окружение
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 3. Установить зависимости
pip install -r requirements.txt

# 4. Настроить переменные окружения
cp .env.example .env
# Отредактировать .env — вписать BOT_TOKEN и ADMIN_IDS

# 5. Извлечь базу знаний из PDF (если нужно пересоздать)
# Положить PDF-файлы в папку "база книг" рядом с проектом
python scripts/extract_pdf_knowledge.py

# 6. Загрузить базу знаний в ChromaDB
python scripts/load_knowledge.py

# 7. Запустить бота
python main.py
```

## Структура проекта

```
telegram-knowledge-bot/
├── .env.example          # Шаблон переменных окружения
├── config.py             # Конфигурация
├── requirements.txt      # Зависимости
├── main.py               # Точка входа
├── bot/
│   ├── handlers/
│   │   ├── user.py       # Обработка сообщений
│   │   ├── admin.py      # Админ-команды
│   │   └── subscription.py # Подписка/оплата
│   ├── middlewares/
│   │   ├── rate_limit.py # Защита от спама
│   │   └── subscription_check.py
│   └── keyboards/
│       └── inline.py     # Inline-кнопки
├── core/
│   ├── normalizer.py     # Транслитерация, очистка текста
│   ├── search_engine.py  # ChromaDB + embeddings
│   └── knowledge_loader.py
├── database/
│   ├── models.py         # SQL-схемы
│   └── db.py             # Работа с SQLite
├── knowledge/            # JSON-файлы базы знаний
├── logs/                 # Логи
└── scripts/
    ├── extract_pdf_knowledge.py # Извлечение Q&A из PDF
    ├── load_knowledge.py        # Загрузка базы знаний в ChromaDB
    └── backup_db.py             # Резервное копирование
```

## Команды бота

| Команда | Описание | Доступ |
|---------|----------|--------|
| /start | Приветствие | Все |
| /help | Справка | Все |
| /stats | Статистика пользователя | Все |
| /admin_stats | Общая статистика | Админ |
| /admin_grant {user_id} | Выдать подписку | Админ |
| /admin_revoke {user_id} | Снять подписку | Админ |
| /admin_reload | Перезагрузить базу знаний | Админ |

## Формат базы знаний

JSON-файлы в директории `knowledge/`:

```json
{
  "knowledge_base": [
    {
      "id": "001",
      "question": "Вопрос",
      "answer": "Точный текст ответа",
      "category": "категория",
      "tags": ["тег1", "тег2"],
      "alt_questions": [
        "Альтернативная формулировка 1",
        "Альтернативная формулировка 2"
      ]
    }
  ]
}
```

### Добавление новых вопросов

1. Добавьте запись в JSON-файл в `knowledge/`
2. Запустите `python scripts/load_knowledge.py` или команду `/admin_reload` в боте

## Бэкап

```bash
# Ручной бэкап
python scripts/backup_db.py

# Автоматический (cron, ежедневно в 3:00)
0 3 * * * cd /path/to/bot && /path/to/venv/bin/python scripts/backup_db.py
```

## Развёртывание (systemd)

```ini
# /etc/systemd/system/knowledge-bot.service
[Unit]
Description=Telegram Knowledge Bot
After=network.target

[Service]
Type=simple
User=bot
WorkingDirectory=/path/to/telegram-knowledge-bot
ExecStart=/path/to/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable knowledge-bot
sudo systemctl start knowledge-bot
```

## Технологии

- Python 3.11+
- aiogram 3.x — асинхронный Telegram API
- sentence-transformers — мультиязычные embeddings
- ChromaDB — векторная база данных
- SQLite + aiosqlite — хранение пользователей
- loguru — логирование
