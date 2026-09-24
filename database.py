import sqlite3
from datetime import datetime, timedelta

DB_PATH = "music_bot.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            query TEXT,
            title TEXT,
            file_id TEXT,
            added_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            query TEXT,
            title TEXT,
            file_id TEXT,
            played_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS banned (
            user_id INTEGER PRIMARY KEY,
            reason TEXT,
            banned_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tracks (
            query TEXT PRIMARY KEY,
            title TEXT,
            artist TEXT,
            file_id TEXT,
            cached_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS premium (
            user_id INTEGER PRIMARY KEY,
            until TEXT,
            bought_at TEXT
        )
    """)

    # Миграция старой БД
    try:
        cur.execute("ALTER TABLE tracks ADD COLUMN artist TEXT")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()


# ============ USERS ============

def add_user(user_id: int, username: str, first_name: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO users (user_id, username, first_name, joined_at)
        VALUES (?, ?, ?, ?)
    """, (user_id, username, first_name, datetime.now().isoformat()))
    conn.commit()
    conn.close()


# ============ CACHE ============

def get_cached_track(query: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT title, artist, file_id FROM tracks WHERE query = ?",
        (query.lower().strip(),)
    )
    row = cur.fetchone()
    conn.close()
    return row


def cache_track(query: str, title: str, artist: str, file_id: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO tracks (query, title, artist, file_id, cached_at)
        VALUES (?, ?, ?, ?, ?)
    """, (query.lower().strip(), title, artist or "Music Bot", file_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def delete_cached_track(query: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM tracks WHERE query = ?", (query.lower().strip(),))
    conn.commit()
    conn.close()


# ============ BANNED ============

def add_banned(user_id: int, reason: str = "spam"):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO banned (user_id, reason, banned_at)
        VALUES (?, ?, ?)
    """, (user_id, reason, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def is_banned(user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM banned WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row is not None


def remove_ban(user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM banned WHERE user_id = ?", (user_id,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def load_all_banned():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM banned")
    rows = cur.fetchall()
    conn.close()
    return [row[0] for row in rows]


# ============ HISTORY ============

def add_history(user_id: int, query: str, title: str, file_id: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO history (user_id, query, title, file_id, played_at)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, query, title, file_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_last_history_id(user_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT id FROM history WHERE user_id = ?
        ORDER BY id DESC LIMIT 1
    """, (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 0


def get_history_by_id(history_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT query, title, file_id FROM history WHERE id = ?", (history_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_history_by_file_id(user_id: int, file_id: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, query FROM history
        WHERE user_id = ? AND file_id = ?
        ORDER BY id DESC LIMIT 1
    """, (user_id, file_id))
    row = cur.fetchone()
    conn.close()
    return row


def get_history(user_id: int, limit: int = 20):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT query, title, file_id FROM history
        WHERE user_id = ?
        ORDER BY played_at DESC
        LIMIT ?
    """, (user_id, limit))
    rows = cur.fetchall()
    conn.close()
    return rows


# ============ LIKES ============

def add_like(user_id: int, query: str, title: str, file_id: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id FROM likes WHERE user_id = ? AND file_id = ?", (user_id, file_id))
    if cur.fetchone():
        conn.close()
        return False

    cur.execute("""
        INSERT INTO likes (user_id, query, title, file_id, added_at)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, query, title, file_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return True


def remove_like(user_id: int, file_id: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM likes WHERE user_id = ? AND file_id = ?", (user_id, file_id))
    conn.commit()
    conn.close()


def remove_like_by_id(like_id: int, user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM likes WHERE id = ? AND user_id = ?", (like_id, user_id))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def get_likes(user_id: int, limit: int = 20):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT query, title, file_id FROM likes
        WHERE user_id = ?
        ORDER BY added_at DESC
        LIMIT ?
    """, (user_id, limit))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_likes_with_id(user_id: int, limit: int = 20):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, query, title, file_id FROM likes
        WHERE user_id = ?
        ORDER BY added_at DESC
        LIMIT ?
    """, (user_id, limit))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_like_by_id(like_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id, query, title, file_id FROM likes WHERE id = ?", (like_id,))
    row = cur.fetchone()
    conn.close()
    return row


def is_liked(user_id: int, file_id: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id FROM likes WHERE user_id = ? AND file_id = ?", (user_id, file_id))
    row = cur.fetchone()
    conn.close()
    return row is not None


# ============ PREMIUM ============

def add_premium(user_id: int, days: int = 30):
    """Дать/продлить премиум на N дней."""
    now = datetime.now()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT until FROM premium WHERE user_id = ?", (user_id,))
    row = cur.fetchone()

    if row and row[0] > now.isoformat():
        old_until = datetime.fromisoformat(row[0])
        new_until = (old_until + timedelta(days=days)).isoformat()
        cur.execute("UPDATE premium SET until = ? WHERE user_id = ?", (new_until, user_id))
    else:
        new_until = (now + timedelta(days=days)).isoformat()
        cur.execute("""
            INSERT OR REPLACE INTO premium (user_id, until, bought_at)
            VALUES (?, ?, ?)
        """, (user_id, new_until, now.isoformat()))

    conn.commit()
    conn.close()


def is_premium(user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT until FROM premium WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return False
    try:
        return row[0] > datetime.now().isoformat()
    except Exception:
        return False


def get_premium_until(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT until FROM premium WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


# ============ STATS (для админа) ============

def get_total_users() -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    n = cur.fetchone()[0]
    conn.close()
    return n


def get_users_today() -> int:
    """Юзеры, которые зашли сегодня (по joined_at)."""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users WHERE joined_at LIKE ?", (f"{today}%",))
    n = cur.fetchone()[0]
    conn.close()
    return n


def get_tracks_today() -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM history WHERE played_at LIKE ?", (f"{today}%",))
    n = cur.fetchone()[0]
    conn.close()
    return n


def get_active_users_today() -> int:
    """Юзеры, которые искали треки сегодня (уникальные)."""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(DISTINCT user_id) FROM history WHERE played_at LIKE ?", (f"{today}%",))
    n = cur.fetchone()[0]
    conn.close()
    return n


def get_total_tracks() -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM history")
    n = cur.fetchone()[0]
    conn.close()
    return n


def get_premium_count() -> int:
    now = datetime.now().isoformat()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM premium WHERE until > ?", (now,))
    n = cur.fetchone()[0]
    conn.close()
    return n


def get_banned_count() -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM banned")
    n = cur.fetchone()[0]
    conn.close()
    return n


def get_top_queries(limit: int = 5):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT query, COUNT(*) as cnt FROM history
        GROUP BY query
        ORDER BY cnt DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows