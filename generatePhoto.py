# main.py
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
import asyncio
import hmac
import hashlib
from urllib.parse import unquote

from PIL import Image
import io

from fastapi import FastAPI, HTTPException, UploadFile, File, status, BackgroundTasks, Header, Depends, Security
from fastapi.security import APIKeyHeader
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import redis

from pydantic import BaseModel
# ✅ Обновляем импорты из вашей базы данных
from database import init_db, get_or_create_user, can_user_generate, get_total_users_count

load_dotenv()

# --- Конфигурация ---
PIAPI_KEY = os.getenv("PIAPI_API_KEY")
IMAGE_DIR = "/app/batyr-images"
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
MAX_POLLING_TIME = 120
POLLING_INTERVAL = 2

if not PIAPI_KEY:
    raise RuntimeError("Не найден PIAPI_API_KEY в .env файле")

# --- Подключение к Redis ---
try:
    redis_pool = redis.ConnectionPool(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
    redis_client = redis.Redis(connection_pool=redis_pool)
    redis_client.ping()
    print(f"✅ Подключено к Redis по адресу: {REDIS_HOST}:{REDIS_PORT}")
except redis.exceptions.ConnectionError as e:
    print(f"❌ Не удалось подключиться к Redis: {e}")
    redis_client = None

# --- Кэш изображений батыров ---
batyr_images_cache: List[Dict[str, str]] = []

def load_batyr_images_to_cache():
    print("⏳ Загрузка и кэширование изображений батыров...")
    # ... (код этой функции не меняется)
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
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
fastapi_kwargs = {"title": "Batyr AI API", "description": "API для замены лиц на изображениях батыров."}
if ENVIRONMENT == "production":
    fastapi_kwargs.update({"docs_url": None, "redoc_url": None, "openapi_url": None})
    print("Main: 'production' mode. API docs disabled.")
else:
    print("Main: 'development' mode. API docs available.")
app = FastAPI(**fastapi_kwargs)

@app.on_event("startup")
def on_startup():
    init_db()
    load_batyr_images_to_cache()
    if not redis_client: raise RuntimeError("Не удалось установить соединение с Redis.")

# --- Middleware для CORS ---
origins = ["http://localhost:3000", "https://batyrai.com", "https://www.batyrai.com", "https://batyr-ai.vercel.app", "https://batyr-ai-madis-projects-f57aa02c.vercel.app"]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- ✅ Безопасная секция авторизации через Telegram initData ---
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN не задан! Сервис не может быть запущен безопасно.")

telegram_init_data_header = APIKeyHeader(name="X-Telegram-Init-Data", auto_error=False)

async def get_validated_telegram_data(init_data: str = Security(telegram_init_data_header)):
    """
    Проверяет подпись initData, создает пользователя в БД и возвращает проверенные данные.
    """
    if not init_data:
        raise HTTPException(status_code=401, detail="X-Telegram-Init-Data header is missing")
    try:
        unquoted_init_data = unquote(init_data)
        data_check_string, hash_from_telegram = [], ''
        for item in sorted(unquoted_init_data.split('&')):
            key, value = item.split('=', 1)
            if key == 'hash':
                hash_from_telegram = value
            else:
                data_check_string.append(f"{key}={value}")
        data_check_string = "\n".join(data_check_string)
        secret_key = hmac.new("WebAppData".encode(), BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        if calculated_hash != hash_from_telegram:
            raise HTTPException(status_code=403, detail="Invalid data signature")

        # Извлекаем данные пользователя из проверенной строки
        user_data_dict = dict(kv.split('=') for kv in unquoted_init_data.split('&'))
        user_data = json.loads(user_data_dict.get('user', '{}'))
        user_id = user_data.get('id')
        if not user_id:
            raise ValueError("User ID not found in validated data")

        # ✅ Создаем пользователя, если его нет
        get_or_create_user(
            user_id=user_id,
            username=user_data.get('username', 'unknown'),
            first_name=user_data.get('first_name', 'unknown')
        )
        
        return user_data
    except Exception as e:
        print(f"Ошибка валидации Telegram initData: {e}")
        raise HTTPException(status_code=403, detail="Could not validate Telegram credentials.")

# --- Модели данных ---
class PhotoSendRequest(BaseModel):
    imageUrl: str

# --- Вспомогательные функции ---
# ... (код вспомогательных функций не меняется) ...

# --- Главные эндпоинты с новой безопасной логикой ---
@app.post("/api/start-face-swap", status_code=status.HTTP_202_ACCEPTED)
async def start_face_swap_task(
    background_tasks: BackgroundTasks,
    user_photo: UploadFile = File(...),
    # ✅ Получаем данные из зависимости, а не из заголовков
    validated_user: dict = Depends(get_validated_telegram_data)
):
    # ✅ Единственный источник правды - ID из проверенных данных!
    user_id = validated_user.get('id')
    if not user_id:
        raise HTTPException(status_code=403, detail="Invalid user data from Telegram.")

    # ✅ Проверяем лимиты для НАСТОЯЩЕГО пользователя
    can_generate, message, remaining_attempts = can_user_generate(user_id=user_id)
    if not can_generate:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=message)

    job_id = str(uuid.uuid4())
    if not user_photo.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Недопустимый тип файла.")
    
    user_photo_bytes = await user_photo.read()
    update_job_status(job_id, {"status": "accepted", "job_id": job_id, "message": "⏳ Генерация изображения..."})
    background_tasks.add_task(run_face_swap_in_background, job_id, user_photo_bytes, user_id)
    
    print(f"👍 [Job: {job_id}] Задача принята для пользователя {user_id} ({validated_user.get('first_name', '')}).")
    return { "job_id": job_id, "status": "accepted", "message": "Задача принята в обработку.", "remaining_attempts": remaining_attempts }

@app.get("/api/task-status/{job_id}", dependencies=[Depends(get_validated_telegram_data)])
async def get_task_status(job_id: str):
    task_data_str = redis_client.get(job_id)
    if not task_data_str:
        raise HTTPException(status_code=404, detail="Задача не найдена.")
    return json.loads(task_data_str)

@app.post("/api/send-photo-to-chat")
async def send_photo_to_chat(
    request: PhotoSendRequest,
    # ✅ Получаем ID из проверенных данных
    validated_user: dict = Depends(get_validated_telegram_data)
):
    user_id = validated_user.get('id')
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise HTTPException(status_code=500, detail="Токен бота не настроен на сервере.")
    
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    payload = { "chat_id": user_id, "photo": request.imageUrl, "caption": "Ваш портрет Батыра готов! ✨\n\nСоздано в @BatyrAI_bot" }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=30.0)
            response.raise_for_status()
        return {"status": "ok", "message": "Фото успешно отправлено в чат."}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Произошла внутренняя ошибка сервера.")

@app.get("/api/download-image", dependencies=[Depends(get_validated_telegram_data)])
async def download_image_proxy(url: str):
    if not url:
        raise HTTPException(status_code=400, detail="URL не указан.")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, follow_redirects=True, timeout=30.0)
            response.raise_for_status()
            content_type = response.headers.get('content-type', 'application/octet-stream')
            return StreamingResponse(response.iter_bytes(), media_type=content_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Произошла внутренняя ошибка при скачивании файла.")

# --- Открытые эндпоинты для мониторинга ---
@app.get("/api/stats")
async def get_app_stats():
    total_users = get_total_users_count()
    return { "total_unique_users": total_users, "timestamp": datetime.now().isoformat() }

@app.get("/api/health")
async def health_check():
    redis_status = "disconnected"
    try:
        if redis_client and redis_client.ping():
            redis_status = "connected"
    except Exception:
        pass
    return { "status": "healthy" if redis_status == "connected" else "unhealthy", "redis": redis_status, "batyr_images_cached": len(batyr_images_cache), "timestamp": datetime.now().isoformat() }