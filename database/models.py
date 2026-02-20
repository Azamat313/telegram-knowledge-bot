"""
SQL-схемы и запросы для работы с SQLite.
"""

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id BIGINT UNIQUE NOT NULL,
    username TEXT,
    first_name TEXT,
    answers_count INTEGER DEFAULT 0,
    is_subscribed BOOLEAN DEFAULT FALSE,
    subscription_expires_at DATETIME NULL,
    city TEXT DEFAULT NULL,
    language TEXT DEFAULT 'kk',
    is_onboarded BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS query_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_telegram_id BIGINT NOT NULL,
    query_text TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    matched_question TEXT,
    answer_text TEXT,
    similarity_score REAL,
    was_answered BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_telegram_id BIGINT NOT NULL,
    plan_name TEXT NOT NULL,
    amount REAL NOT NULL,
    currency TEXT DEFAULT 'XTR',
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    payment_method TEXT,
    payment_id TEXT,
    telegram_payment_charge_id TEXT
);

CREATE TABLE IF NOT EXISTS conversation_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_telegram_id BIGINT NOT NULL,
    role TEXT NOT NULL,
    message_text TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ustaz_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id BIGINT UNIQUE NOT NULL,
    username TEXT,
    first_name TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    max_queue_size INTEGER DEFAULT 10,
    total_answered INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS consultations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_telegram_id BIGINT NOT NULL,
    ustaz_telegram_id BIGINT,
    question_text TEXT NOT NULL,
    ai_answer_text TEXT,
    conversation_context TEXT,
    answer_text TEXT,
    status TEXT DEFAULT 'pending',
    query_log_id INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    answered_at DATETIME,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ustaz_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_telegram_id BIGINT NOT NULL,
    month_year TEXT NOT NULL,
    used_count INTEGER DEFAULT 0,
    UNIQUE(user_telegram_id, month_year)
);

CREATE TABLE IF NOT EXISTS ramadan_schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city TEXT NOT NULL,
    day_number INTEGER NOT NULL,
    gregorian_date TEXT NOT NULL,
    day_of_week TEXT NOT NULL,
    fajr TEXT NOT NULL,
    sunrise TEXT NOT NULL,
    dhuhr TEXT NOT NULL,
    asr TEXT NOT NULL,
    maghrib TEXT NOT NULL,
    isha TEXT NOT NULL,
    is_special BOOLEAN DEFAULT FALSE,
    special_name_kk TEXT,
    special_name_ru TEXT,
    UNIQUE(city, day_number)
);

CREATE TABLE IF NOT EXISTS moderator_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_telegram_id BIGINT NOT NULL,
    message_text TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    moderator_response TEXT,
    responded_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS prayer_times_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city_name TEXT NOT NULL,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    date TEXT NOT NULL,
    imsak TEXT,
    fajr TEXT,
    sunrise TEXT,
    dhuhr TEXT,
    asr TEXT,
    maghrib TEXT,
    isha TEXT,
    fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(lat, lng, date)
);

CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
CREATE INDEX IF NOT EXISTS idx_query_logs_user ON query_logs(user_telegram_id);
CREATE INDEX IF NOT EXISTS idx_query_logs_created ON query_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_telegram_id);
CREATE INDEX IF NOT EXISTS idx_conversation_history_user ON conversation_history(user_telegram_id);
CREATE INDEX IF NOT EXISTS idx_ustaz_profiles_telegram_id ON ustaz_profiles(telegram_id);
CREATE INDEX IF NOT EXISTS idx_consultations_status ON consultations(status);
CREATE INDEX IF NOT EXISTS idx_consultations_user ON consultations(user_telegram_id);
CREATE INDEX IF NOT EXISTS idx_consultations_ustaz ON consultations(ustaz_telegram_id);
CREATE INDEX IF NOT EXISTS idx_ustaz_usage_user_month ON ustaz_usage(user_telegram_id, month_year);
CREATE INDEX IF NOT EXISTS idx_ramadan_schedule_city ON ramadan_schedule(city);
CREATE INDEX IF NOT EXISTS idx_moderator_tickets_status ON moderator_tickets(status);
CREATE INDEX IF NOT EXISTS idx_moderator_tickets_user ON moderator_tickets(user_telegram_id);
CREATE INDEX IF NOT EXISTS idx_prayer_cache_coords_date ON prayer_times_cache(lat, lng, date);

CREATE TABLE IF NOT EXISTS kaspi_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_telegram_id BIGINT NOT NULL,
    payment_code TEXT,
    amount_expected REAL NOT NULL,
    amount_found REAL,
    comment_found TEXT,
    receipt_file_id TEXT,
    status TEXT DEFAULT 'pending',
    plan_days INTEGER DEFAULT 30,
    verified_by TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    verified_at DATETIME
);
CREATE INDEX IF NOT EXISTS idx_kaspi_payments_user ON kaspi_payments(user_telegram_id);
CREATE INDEX IF NOT EXISTS idx_kaspi_payments_status ON kaspi_payments(status);
"""
