# database.py
import sqlite3
import datetime
import os # ✅ Добавляем импорт os
from pathlib import Path
from typing import Tuple

# --- Константы и инициализация ---
DB_FILE = Path("storage/users.db")
DAILY_LIMIT = 1 
# ✅ Получаем ID админа из переменных окружения
ADMIN_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "0"))

def init_db():
    """Инициализирует базу данных и создает таблицу, если она не существует."""
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
        if ADMIN_ID != 0:
            print(f"👑 Пользователь с ID {ADMIN_ID} является админом.")
    except Exception as e:
        print(f"🔥 Критическая ошибка при инициализации БД: {e}")
        raise

# --- Безопасная логика работы с пользователями ---

def get_or_create_user(user_id: int, username: str, first_name: str) -> None:
    """
    Проверяет, существует ли пользователь. Если нет - создает его.
    Вызывается только с проверенными данными из initData.
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        today_str = datetime.date.today().isoformat()

        cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
        user_exists = cursor.fetchone()

        if not user_exists:
            cursor.execute(
                "INSERT INTO users (user_id, username, first_name, usage_count, last_usage_date, first_seen_date) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, username, first_name, 0, '1970-01-01', today_str)
            )
            conn.commit()
            print(f"✅ Новый пользователь {user_id} ({first_name}) зарегистрирован в системе.")

    except Exception as e:
        print(f"🔥 Ошибка в get_or_create_user для user_id {user_id}: {e}")
    finally:
        if conn:
            conn.close()


def can_user_generate(user_id: int) -> Tuple[bool, str, int]:
    """
    Проверяет, может ли пользователь генерировать, и списывает попытку.
    Админы имеют бесконечные попытки.
    """
    # ✅ Проверка на админа в самом начале
    if user_id == ADMIN_ID:
        return True, "👑 Админу можно всё!", 999 # Возвращаем условное большое число попыток

    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        today_str = datetime.date.today().isoformat()

        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user_data = cursor.fetchone()

        if user_data is None:
            return False, "Пользователь не найден. Пожалуйста, перезапустите приложение.", 0

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
        if conn:
            conn.close()

def get_total_users_count() -> int:
    """Подсчитывает общее количество пользователей в базе."""
    conn = None
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
        if conn:
            conn.close()