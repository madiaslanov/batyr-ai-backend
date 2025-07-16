# Полностью замените содержимое файла database.py

import sqlite3
import datetime
import os
from pathlib import Path
from typing import Tuple, Dict

# --- Константы и инициализация ---
DB_FILE = Path("storage/users.db")
ADMIN_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "0"))
# Только бесплатные кредиты на генерацию фото при регистрации
INITIAL_CREDITS = 1

def init_db():
    """Инициализирует базу данных и создает таблицу, если ее нет."""
    try:
        DB_FILE.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Создаем таблицу только с необходимыми полями
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                generation_credits INTEGER DEFAULT 0,
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

def get_db_connection():
    """Возвращает соединение с БД."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def get_or_create_user(user_id: int, username: str, first_name: str) -> None:
    """Создает пользователя, если он не существует, и начисляет начальные кредиты на генерацию."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        user_exists = cursor.fetchone()

        if not user_exists:
            today_str = datetime.date.today().isoformat()
            cursor.execute(
                "INSERT INTO users (user_id, username, first_name, generation_credits, first_seen_date) VALUES (?, ?, ?, ?, ?)",
                (user_id, username, first_name, INITIAL_CREDITS, today_str)
            )
            conn.commit()
            print(f"✅ Новый пользователь {user_id} ({first_name}) зарегистрирован. Начислено {INITIAL_CREDITS} кредитов на генерацию.")
    except Exception as e:
        print(f"🔥 Ошибка в get_or_create_user для user_id {user_id}: {e}")
    finally:
        conn.close()

def can_user_generate(user_id: int) -> Tuple[bool, str, int]:
    """Проверяет и списывает кредиты на ГЕНЕРАЦИЮ ФОТО."""
    if user_id == ADMIN_ID:
        return True, "👑 Админу можно всё!", 999

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT generation_credits FROM users WHERE user_id = ?", (user_id,))
        user_data = cursor.fetchone()

        if user_data is None:
            return False, "Пользователь не найден. Пожалуйста, перезапустите приложение.", 0

        credits = user_data['generation_credits']
        
        if credits > 0:
            new_credits = credits - 1
            cursor.execute("UPDATE users SET generation_credits = ? WHERE user_id = ?", (new_credits, user_id))
            conn.commit()
            return True, "Кредит списан. Генерация разрешена.", new_credits
        else:
            return False, "У вас закончились кредиты на генерацию фото. Пополните баланс.", 0
    except Exception as e:
        print(f"🔥 Ошибка в can_user_generate для user_id {user_id}: {e}")
        return False, "Произошла ошибка при проверке баланса.", 0
    finally:
        conn.close()

def add_credits_to_user(user_id: int, amount: int) -> int:
    """Добавляет кредиты на ГЕНЕРАЦИЮ ФОТО."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET generation_credits = generation_credits + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        
        cursor.execute("SELECT generation_credits FROM users WHERE user_id = ?", (user_id,))
        new_balance = cursor.fetchone()['generation_credits']
        print(f"💰 Пользователю {user_id} начислено {amount} кредитов. Новый баланс: {new_balance}")
        return new_balance
    except Exception as e:
        print(f"🔥 Ошибка в add_credits_to_user для user_id {user_id}: {e}")
        return -1
    finally:
        conn.close()

def get_total_users_count() -> int:
    """Подсчитывает общее количество пользователей в базе."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(user_id) FROM users")
        count = cursor.fetchone()[0]
        return count
    except Exception as e:
        print(f"🔥 Ошибка при подсчете пользователей: {e}")
        return 0
    finally:
        conn.close()