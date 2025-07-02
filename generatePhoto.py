import os
import httpx
import base64
import traceback
import random
import uuid
import json
import time
from datetime import datetime
from typing import List, Dict, Optional

# <<< ДОБАВЛЕНО: Импорты для работы с заголовками и нашей БД
from fastapi import FastAPI, HTTPException, UploadFile, File, status, BackgroundTasks, Header
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import redis

# <<< ДОБАВЛЕНО: Импортируем функции из нашего файла database.py
from database import init_db, can_user_generate, get_total_users_count

load_dotenv()

# --- Конфигурация ---
PIAPI_KEY = os.getenv("PIAPI_API_KEY")
IMAGE_DIR = "/app/batyr-images"
REDIS_HOST = os.getenv("REDIS_HOST", "redis") # <<< ИЗМЕНЕНО: Для Docker лучше использовать имя сервиса
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# Настройки таймаутов
MAX_POLLING_TIME = 120
POLLING_INTERVAL = 2

if not PIAPI_KEY:
    raise RuntimeError("Не найден PIAPI_API_KEY в .env файле")

# --- Подключение к Redis ---
# (Ваш код подключения к Redis остается без изменений)
try:
    redis_pool = redis.ConnectionPool(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
    redis_client = redis.Redis(connection_pool=redis_pool)
    redis_client.ping()
    print(f"✅ Подключено к Redis по адресу: {REDIS_HOST}:{REDIS_PORT}")
except redis.exceptions.ConnectionError as e:
    print(f"❌ Не удалось подключиться к Redis: {e}")
    redis_client = None

# --- Кэш изображений батыров в памяти ---
# (Ваш код кэширования изображений остается без изменений)
batyr_images_cache: List[Dict[str, str]] = []

def load_batyr_images_to_cache():
    """Загружает и кодирует изображения батыров в кэш."""
    print("⏳ Загрузка и кэширование изображений батыров...")
    # ... (весь ваш код этой функции без изменений)
    try:
        if not os.path.exists(IMAGE_DIR):
            print(f"⚠️ Директория {IMAGE_DIR} не найдена.")
            return
        for filename in os.listdir(IMAGE_DIR):
            if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                image_path = os.path.join(IMAGE_DIR, filename)
                try:
                    with open(image_path, "rb") as image_file:
                        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                        mime_type = f"image/{filename.split('.')[-1].lower().replace('jpg', 'jpeg')}"
                        data_uri = f"data:{mime_type};base64,{encoded_string}"
                        batyr_images_cache.append({"name": filename, "data_uri": data_uri})
                except Exception as e:
                    print(f"⚠️ Не удалось обработать файл {filename}: {e}")
        if batyr_images_cache:
            print(f"✅ Успешно закэшировано {len(batyr_images_cache)} изображений.")
        else:
            print("❌ Изображения для кэширования не найдены.")
    except Exception as e:
        print(f"🔥 Критическая ошибка при кэшировании изображений: {e}")

# --- Приложение FastAPI ---
app = FastAPI(
    title="Batyr AI API",
    description="API для замены лиц на изображениях батыров с системой лимитов."
)

@app.on_event("startup")
def on_startup():
    """Выполняется при старте приложения."""
    # <<< ДОБАВЛЕНО: Инициализация базы данных пользователей
    init_db()
    
    load_batyr_images_to_cache()
    if not redis_client:
        raise RuntimeError("Не удалось установить соединение с Redis. Приложение не может запуститься.")

# --- Middleware для CORS ---
origins = [
    "https://batyrai.com",     # Ваш основной домен
    "http://localhost",         # Оставим на всякий случай для тестов
    "http://localhost:3000",    # И этот тоже
    "http://localhost:8000",
    "http://localhost:80",
    "https://batyr-ai.vercel.app"
]
# (Ваш код middleware остается без изменений)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,      # <<< Используем наш новый список
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Вспомогательные функции и фоновая задача ---
# (Все ваши функции get_random_batyr_image_uri, update_job_status, run_face_swap_in_background остаются без изменений)
def get_random_batyr_image_uri():
    # ...
    if not batyr_images_cache:
        raise ValueError("Кэш изображений батыров пуст.")
    return random.choice(batyr_images_cache)['data_uri']

def update_job_status(job_id: str, status_data: dict):
    # ...
    try:
        redis_client.set(job_id, json.dumps(status_data), ex=3600) 
        print(f"📝 [Job: {job_id}] Статус обновлен: {status_data.get('status', 'N/A')}")
    except Exception as e:
        print(f"❌ [Job: {job_id}] Ошибка обновления статуса в Redis: {e}")

def run_face_swap_in_background(job_id: str, user_photo_data_uri: str):
    # ... (весь ваш код этой функции без изменений)
    # Этот код теперь будет запускаться только ПОСЛЕ проверки лимита
    try:
        update_job_status(job_id, {"status": "preparing", "message": "Подготовка изображений"})
        target_image_uri = get_random_batyr_image_uri()
        headers = {"x-api-key": PIAPI_KEY, "Content-Type": "application/json"}
        payload = {"model": "Qubico/image-toolkit", "task_type": "face-swap", "input": {"target_image": target_image_uri, "swap_image": user_photo_data_uri,}}
        
        update_job_status(job_id, {"status": "sending", "message": "Отправка запроса в PiAPI"})
        with httpx.Client(timeout=30.0) as client:
            response = client.post("https://api.piapi.ai/api/v1/task", headers=headers, json=payload)
            response.raise_for_status()
            task_response = response.json()
        piapi_task_id = task_response.get("data", {}).get("task_id")
        if not piapi_task_id:
            raise ValueError(f"Не получен task_id от PiAPI: {task_response}")

        start_time = time.monotonic()
        while time.monotonic() - start_time < MAX_POLLING_TIME:
            time.sleep(POLLING_INTERVAL)
            with httpx.Client(timeout=15.0) as client:
                res = client.get(f"https://api.piapi.ai/api/v1/task/{piapi_task_id}", headers=headers)
            if res.status_code == 200:
                piapi_data = res.json().get("data", {})
                piapi_status = piapi_data.get("status", "Unknown").title()
                if piapi_status == "Completed":
                    result_url = piapi_data.get("output", {}).get("image_url")
                    update_job_status(job_id, {"status": "completed", "result_url": result_url})
                    return
                elif piapi_status == "Failed":
                    error_details = piapi_data.get("error", "Неизвестная ошибка PiAPI")
                    update_job_status(job_id, {"status": "failed", "error": f"PiAPI ошибка: {error_details}"})
                    return
                elif piapi_status in ["Processing", "Pending", "Staged"]:
                    update_job_status(job_id, {"status": "processing", "piapi_status": piapi_status})
                else:
                    update_job_status(job_id, {"status": "failed", "error": f"Неизвестный статус PiAPI: {piapi_status}"})
                    return
        update_job_status(job_id, {"status": "timeout", "error": f"Превышено время ожидания ({MAX_POLLING_TIME}с)"})
    except Exception as e:
        error_msg = f"Критическая ошибка в фоновой задаче: {str(e)}"
        traceback.print_exc()
        update_job_status(job_id, {"status": "failed", "error": error_msg})


# <<< ГЛАВНЫЕ ИЗМЕНЕНИЯ ЗДЕСЬ >>>
@app.post("/api/start-face-swap", status_code=status.HTTP_202_ACCEPTED)
async def start_face_swap_task(
    background_tasks: BackgroundTasks, 
    user_photo: UploadFile = File(...),
    # Получаем данные о пользователе из HTTP заголовков
    x_telegram_user_id: int = Header(..., description="Уникальный ID пользователя Telegram"),
    x_telegram_username: Optional[str] = Header(None, description="Username пользователя Telegram"),
    x_telegram_first_name: Optional[str] = Header(None, description="Имя пользователя Telegram")
):
    """
    Принимает фото, проверяет лимит пользователя и запускает обработку в фоне.
    """
    # 1. Проверяем лимит пользователя ПЕРЕД любыми действиями
    can_generate, message, remaining_attempts = await can_user_generate(
        user_id=x_telegram_user_id,
        username=x_telegram_username or "N/A",
        first_name=x_telegram_first_name or "N/A"
    )

    if not can_generate:
        # Если лимит исчерпан, возвращаем ошибку 429 Too Many Requests
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=message
        )

    # 2. Если лимит в порядке, продолжаем старую логику
    job_id = str(uuid.uuid4())
    try:
        if not user_photo.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Недопустимый тип файла.")

        user_photo_bytes = await user_photo.read()
        user_photo_base64 = base64.b64encode(user_photo_bytes).decode('utf-8')
        user_photo_data_uri = f"data:{user_photo.content_type};base64,{user_photo_base64}"
        
        initial_status = {"status": "accepted", "job_id": job_id}
        update_job_status(job_id, initial_status)

        background_tasks.add_task(run_face_swap_in_background, job_id, user_photo_data_uri)
        
        print(f"👍 [Job: {job_id}] Задача принята для пользователя {x_telegram_user_id}.")
        return {
            "job_id": job_id, 
            "status": "accepted", 
            "message": "Задача принята в обработку.",
            "remaining_attempts": remaining_attempts
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при запуске задачи: {str(e)}")

# --- Эндпоинты для статуса и аналитики ---

@app.get("/api/task-status/{job_id}")
async def get_task_status(job_id: str):
    # (Ваш код этой функции остается без изменений)
    try:
        task_data_str = redis_client.get(job_id)
        if not task_data_str:
            raise HTTPException(status_code=404, detail="Задача не найдена.")
        return json.loads(task_data_str)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка сервера.")

# <<< ДОБАВЛЕНО: Новый эндпоинт для статистики >>>
@app.get("/api/stats")
async def get_app_stats():
    """Возвращает общую статистику по приложению."""
    total_users = await get_total_users_count()
    return {
        "total_unique_users": total_users,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/health")
async def health_check():
    # (Ваш код этой функции остается без изменений)
    redis_status = "disconnected"
    try:
        if redis_client and redis_client.ping():
            redis_status = "connected"
    except Exception:
        pass
    
    return {
        "status": "healthy" if redis_status == "connected" else "unhealthy",
        "redis": redis_status,
        "batyr_images_cached": len(batyr_images_cache),
        "timestamp": datetime.now().isoformat()
    }