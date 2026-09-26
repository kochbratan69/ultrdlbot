import sqlite3
import os
import time
import config

DB_PATH = os.path.join(config.BASE_DIR, "database.db")

def init_db():
    """Инициализация таблицы базы данных SQLite"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shared_files (
                shortcode TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                filename TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                access_key TEXT NOT NULL
            )
        """)
        # Миграция: если база создана ранее без колонки access_key
        try:
            cursor.execute("ALTER TABLE shared_files ADD COLUMN access_key TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        conn.commit()

def add_share_link(shortcode: str, file_path: str, filename: str, expires_at: int, access_key: str):
    """Сохранение новой короткой ссылки и её ключа в базу"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO shared_files (shortcode, file_path, filename, created_at, expires_at, access_key)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (shortcode, file_path, filename, int(time.time()), expires_at, access_key))
        conn.commit()

def get_share_link(shortcode: str) -> dict | None:
    """Получение информации о файле и ключе доступа по шорткоду"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT file_path, filename, expires_at, access_key FROM shared_files WHERE shortcode = ?
        """, (shortcode,))
        row = cursor.fetchone()
        if row:
            return {
                "file_path": row[0], 
                "filename": row[1], 
                "expires_at": row[2],
                "access_key": row[3]
            }
        return None

def clean_expired_shares():
    """Удаление просроченных записей и файлов с диска"""
    now = int(time.time())
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT shortcode, file_path FROM shared_files WHERE expires_at < ?", (now,))
        expired = cursor.fetchall()
        
        for _, file_path in expired:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
        
        cursor.execute("DELETE FROM shared_files WHERE expires_at < ?", (now,))
        conn.commit()