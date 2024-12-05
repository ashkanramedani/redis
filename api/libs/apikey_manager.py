import sqlite3
from contextlib import contextmanager
from fastapi import Header, HTTPException

# نام فایل پایگاه داده
DB_NAME = "/app/config/apikeys.db"

# مدیریت اتصال به دیتابیس
@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# مقداردهی اولیه پایگاه داده
def initialize_db():
    """ایجاد جدول API Key‌ها در صورت عدم وجود"""
    with get_db_connection() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        conn.commit()

# افزودن API Key جدید
def add_api_key(api_key: str, description: str = None):
    """افزودن API Key جدید به پایگاه داده"""
    with get_db_connection() as conn:
        conn.execute("""
        INSERT INTO api_keys (key, description) VALUES (?, ?)
        """, (api_key, description))
        conn.commit()

# اعتبارسنجی API Key
def validate_api_key(api_key: str) -> bool:
    """بررسی صحت API Key در پایگاه داده"""
    with get_db_connection() as conn:
        result = conn.execute("""
        SELECT 1 FROM api_keys WHERE key = ?
        """, (api_key,)).fetchone()
        return result is not None

# Dependency برای FastAPI
def validate_api_key_dependency(x_api_key: str = Header(...)):
    """Dependency برای بررسی API Key در درخواست‌ها"""
    if not validate_api_key(x_api_key):
        raise HTTPException(status_code=403, detail="Invalid API Key")
