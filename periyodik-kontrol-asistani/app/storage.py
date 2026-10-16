import sqlite3
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    text_excerpt TEXT,
    char_count INTEGER DEFAULT 0,
    uploaded_at TEXT DEFAULT (datetime('now'))
);

-- Her "Periyodik Kontrolleri Çıkart" çalıştırması bir kontrol seti üretir.
CREATE TABLE IF NOT EXISTS control_sets (
    id TEXT PRIMARY KEY,
    baslik TEXT,
    ozet TEXT,
    bosluklar TEXT,            -- JSON liste
    belge_adlari TEXT,         -- JSON liste
    model TEXT,
    durum TEXT DEFAULT 'uretiliyor',   -- uretiliyor | hazir | hata
    hata TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,      -- control_sets.id
    kontrol_adi TEXT,
    kategori TEXT,
    hat TEXT,
    siklik TEXT,
    risk TEXT,
    efor TEXT,
    gerekce TEXT,
    dayanak TEXT,
    kaynak TEXT,
    status TEXT DEFAULT 'bekliyor',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    suggestion_id INTEGER NOT NULL,
    karar TEXT NOT NULL,
    not_metni TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (suggestion_id) REFERENCES suggestions(id)
);

-- Kabul edilen kontroller setler arası tekrar kullanılmak üzere burada birikir.
CREATE TABLE IF NOT EXISTS library (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    suggestion_id INTEGER UNIQUE,
    set_id TEXT,
    kontrol_adi TEXT,
    kategori TEXT,
    hat TEXT,
    siklik TEXT,
    risk TEXT,
    efor TEXT,
    gerekce TEXT,
    dayanak TEXT,
    added_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS set_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    set_id TEXT NOT NULL,
    control_id INTEGER,
    role TEXT NOT NULL,        -- user | ai
    content TEXT,
    changes TEXT,              -- JSON
    lesson TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_suggestions_run ON suggestions(run_id);
CREATE INDEX IF NOT EXISTS idx_feedback_sugg ON feedback(suggestion_id);
CREATE INDEX IF NOT EXISTS idx_messages_set ON set_messages(set_id);
"""

# Eski veritabanlarına sonradan eklenen sütunlar
MIGRATIONS = {
    "documents": {"char_count": "INTEGER DEFAULT 0", "uyari": "TEXT"},
    "suggestions": {"dayanak": "TEXT", "kaynak": "TEXT", "kaynak_belge": "TEXT",
                    "kaynak_bolum": "TEXT", "kaynak_dogrulandi": "INTEGER"},
    "control_sets": {"progress": "TEXT", "istatistik": "TEXT", "iptal": "INTEGER DEFAULT 0"},
}


def get_conn():
    # Üretim arka planda ayrı bir iş parçacığında yazar; kısa kilitlerde beklesin.
    conn = sqlite3.connect(config.DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            for col, decl in cols.items():
                if col not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        conn.commit()
    finally:
        conn.close()


@contextmanager
def db_session():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
