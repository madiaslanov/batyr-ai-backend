# database.py
import sqlite3
import datetime
from pathlib import Path

DB_FILE = Path("storage/users.db")
DAILY_LIMIT = 1 

def init_db():
    try:
        DB_FILE.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                usage_count INTEGER DEFAULT 0,
                last_usage_date TEXT NOT NULL,
                first_seen_date TEXT NOT NULL
            )
        ''')
        conn.commit()
        conn.close()
        print(f"✅ База данных инициализирована: {DB_FILE}")
    except Exception as e:
        print(f"🔥 Критическая ошибка при инициализации БД: {e}")
        raise

async def can_user_generate(user_id: int, username: str, first_name: str) -> (bool, str, int):
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        today_str = datetime.date.today().isoformat()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user_data = cursor.fetchone()

        if user_data is None:
            cursor.execute(
                "INSERT INTO users (user_id, username, first_name, usage_count, last_usage_date, first_seen_date) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, username, first_name, 0, '1970-01-01', today_str)
            )
            conn.commit()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            user_data = cursor.fetchone()
        
        last_date_str = user_data['last_usage_date']
        current_usage = user_data['usage_count']

        if last_date_str != today_str:
            current_usage = 0
        
        if current_usage < DAILY_LIMIT:
            new_count = current_usage + 1
            cursor.execute(
                "UPDATE users SET usage_count = ?, last_usage_date = ? WHERE user_id = ?",
                (new_count, today_str, user_id)
            )
            conn.commit()
            remaining = DAILY_LIMIT - new_count
            return True, f"Генерация разрешена. Осталось сегодня: {remaining}", remaining
        else:
            return False, f"Дневной лимит ({DAILY_LIMIT}) исчерпан. Возвращайтесь завтра!", 0

    except Exception as e:
        print(f"🔥 Ошибка в can_user_generate для user_id {user_id}: {e}")
        return False, "Произошла ошибка при проверке лимита.", 0
    finally:
        if 'conn' in locals() and conn:
            conn.close()

async def get_total_users_count() -> int:
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(user_id) FROM users")
        count = cursor.fetchone()[0]
        return count
    except Exception as e:
        print(f"🔥 Ошибка при подсчете пользователей: {e}")
        return 0
    finally:
        if 'conn' in locals() and conn:
            conn.close()