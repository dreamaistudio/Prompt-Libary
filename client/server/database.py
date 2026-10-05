# ── database.py ── SQLite helpers for Prompt Library ──

import os
import sqlite3
from werkzeug.security import generate_password_hash

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "prompts.db"))


def get_db():
    """Return a new SQLite connection (row_factory = dict)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist."""
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT    UNIQUE NOT NULL,
            password    TEXT    NOT NULL,
            avatar      TEXT    DEFAULT '',
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS prompts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            title       TEXT    NOT NULL,
            prompt      TEXT    NOT NULL,
            category    TEXT    NOT NULL DEFAULT 'Image',
            model       TEXT    DEFAULT '',
            tags        TEXT    DEFAULT '',
            thumbnail   TEXT    DEFAULT '',
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS bookmarks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            prompt_id   INTEGER NOT NULL,
            UNIQUE(user_id, prompt_id),
            FOREIGN KEY (user_id)   REFERENCES users(id),
            FOREIGN KEY (prompt_id) REFERENCES prompts(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS tokens (
            token       TEXT PRIMARY KEY,
            user_id     INTEGER NOT NULL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    """)
    
    # Migration: Add avatar column if missing (for existing installs)
    try:
        db.execute("ALTER TABLE users ADD COLUMN avatar TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # Column likely exists

    # Migration: Add google_id column if missing
    try:
        db.execute("ALTER TABLE users ADD COLUMN google_id TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # Column likely exists

    # Migration: Add reference_images column if missing
    try:
        db.execute("ALTER TABLE prompts ADD COLUMN reference_images TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # Column likely exists

    # Migration: Add instructions column if missing
    try:
        db.execute("ALTER TABLE prompts ADD COLUMN instructions TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # Column likely exists

    # Migration: Add security columns to users table
    for col_def in [
        "email TEXT",
        "totp_secret TEXT",
        "is_totp_enabled INTEGER DEFAULT 0",
        "reset_token TEXT",
        "reset_expires_at TEXT"
    ]:
        try:
            db.execute(f"ALTER TABLE users ADD COLUMN {col_def}")
        except sqlite3.OperationalError:
            pass  # Column likely exists

    db.commit()
    db.close()



