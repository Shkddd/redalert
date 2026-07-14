"""SQLite 表结构 + 初始化"""
import sqlite3
import hashlib
from contextlib import contextmanager
from app.core.config import SQLITE_PATH, DEFAULT_ADMIN


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin','editor','viewer')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL,           -- pdf / excel
    file_path TEXT NOT NULL,
    file_hash TEXT NOT NULL,            -- 去重
    business_category TEXT DEFAULT '通用',
    current_version INTEGER DEFAULT 1,
    uploaded_by INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(uploaded_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    version_no INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    chunk_count INTEGER DEFAULT 0,
    change_note TEXT,
    created_by INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(document_id, version_no),
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(created_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    version_id INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    summary TEXT,
    business_category TEXT DEFAULT '通用',
    page_no INTEGER,
    doc_title TEXT DEFAULT '',
    section_path TEXT DEFAULT '',
    image_id TEXT,
    image_caption TEXT,
    image_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(version_id) REFERENCES versions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_id TEXT UNIQUE NOT NULL,
    document_id INTEGER NOT NULL,
    version_id INTEGER NOT NULL,
    page_no INTEGER,
    section_path TEXT DEFAULT '',
    mime TEXT,
    width INTEGER,
    height INTEGER,
    byte_size INTEGER,
    url TEXT NOT NULL,
    caption TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(version_id) REFERENCES versions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    document_id INTEGER NOT NULL,
    permission TEXT NOT NULL CHECK(permission IN ('read','write','owner')),
    granted_by INTEGER NOT NULL,
    granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, document_id),
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(granted_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS query_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    query TEXT NOT NULL,
    result_count INTEGER,
    latency_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc_ver ON chunks(document_id, version_id);
CREATE INDEX IF NOT EXISTS idx_versions_doc ON versions(document_id, version_no);
CREATE INDEX IF NOT EXISTS idx_perm_user ON permissions(user_id);
"""


def hash_password(pwd: str) -> str:
    return hashlib.sha256(pwd.encode()).hexdigest()


def verify_password(pwd: str, hashed: str) -> bool:
    return hash_password(pwd) == hashed


@contextmanager
def get_conn():
    conn = sqlite3.connect(str(SQLITE_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate_columns(conn):
    """给老库补列:幂等 ALTER,字段已存在则忽略"""
    new_cols = [
        ("chunks", "doc_title", "TEXT DEFAULT ''"),
        ("chunks", "section_path", "TEXT DEFAULT ''"),
        ("chunks", "image_id", "TEXT"),
        ("chunks", "image_caption", "TEXT"),
        ("chunks", "image_url", "TEXT"),
    ]
    for table, col, decl in new_cols:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        except Exception:
            # 重复列报错 → 忽略
            pass


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate_columns(conn)
        # 建默认 admin
        cur = conn.execute("SELECT id FROM users WHERE username=?", (DEFAULT_ADMIN["username"],))
        if cur.fetchone() is None:
            conn.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
                (DEFAULT_ADMIN["username"], hash_password(DEFAULT_ADMIN["password"]), DEFAULT_ADMIN["role"]),
            )
            # 同时建个 editor / viewer
            for u in [("editor", "editor123", "editor"), ("viewer", "viewer123", "viewer")]:
                conn.execute(
                    "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
                    (u[0], hash_password(u[1]), u[2]),
                )
            print("[init_db] 默认用户已建: admin/admin123, editor/editor123, viewer/viewer123")