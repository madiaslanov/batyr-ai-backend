import os
import httpx
import base64
import traceback
import random
import uuid
import json
import time
from datetime import datetime, timedelta
from typing import List, Dict

from fastapi import FastAPI, HTTPException, UploadFile, File, status, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import redis

load_dotenv()

# --- Конфигурация ---
PIAPI_KEY = os.getenv("PIAPI_API_KEY")
IMAGE_DIR = "/app/batyr-images" # Убедись, что этот путь правильный в Docker-контейнере
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# Настройки таймаутов
MAX_POLLING_TIME = 120  # Максимальное время опроса (2 минуты)
POLLING_INTERVAL = 2    # Интервал между запросами (2 секунды)
MAX_RETRIES = 3         # Максимальное количество попыток при ошибках

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
    redis_client = None # Установим в None, чтобы приложение упало при попытке использования

# --- Кэш изображений батыров в памяти ---
# УЛУЧШЕНИЕ: Загружаем изображения один раз при старте, а не при каждом запросе
batyr_images_cache: List[Dict[str, str]] = []

def load_batyr_images_to_cache():
    """Загружает и кодирует изображения батыров в кэш."""
    print("⏳ Загрузка и кэширование изображений батыров...")
    try:
        if not os.path.exists(IMAGE_DIR):
            print(f"⚠️ Директория {IMAGE_DIR} не найдена. Изображения батыров не будут загружены.")
            return
            
        for filename in os.listdir(IMAGE_DIR):
            if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                image_path = os.path.join(IMAGE_DIR, filename)
                try:
                    with open(image_path, "rb") as image_file:
                        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                        
                        # Определяем MIME-тип по расширению файла
                        mime_type = f"image/{filename.split('.')[-1].lower()}"
                        if mime_type == "image/jpg": mime_type = "image/jpeg"

                        # ИСПРАВЛЕНИЕ: Сразу формируем полный Data URI
                        data_uri = f"data:{mime_type};base64,{encoded_string}"
                        
                        batyr_images_cache.append({"name": filename, "data_uri": data_uri})
                except Exception as e:
                    print(f"⚠️ Не удалось прочитать или закодировать файл {filename}: {e}")
        
        if batyr_images_cache:
            print(f"✅ Успешно закэшировано {len(batyr_images_cache)} изображений батыров.")
        else:
            print("❌ На сервере не найдены подходящие изображения батыров для кэширования.")

    except Exception as e:
        print(f"🔥 Критическая ошибка при кэшировании изображений: {e}")
        traceback.print_exc()

# --- Приложение FastAPI ---
app = FastAPI(
    title="Batyr AI API",
    description="API для замены лиц на изображениях батыров."
)

@app.on_event("startup")
def on_startup():
    """Выполняется при старте приложения."""
    load_batyr_images_to_cache()
    if not redis_client:
        raise RuntimeError("Не удалось установить соединение с Redis. Приложение не может запуститься.")


app.add_middleware(
    CORSMiddleware,
    # УЛУЧШЕНИЕ: В продакшене замени "*" на домен твоего фронтенда
    allow_origins=["*"], # Например: ["https://your-frontend.com", "http://localhost:3000"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_random_batyr_image_uri():
    """УЛУЧШЕНИЕ: Получает случайное изображение из кэша."""
    if not batyr_images_cache:
        raise ValueError("Кэш изображений батыров пуст. Проверьте логи сервера.")
    return random.choice(batyr_images_cache)['data_uri']

def update_job_status(job_id: str, status_data: dict):
    """Обновить статус задачи в Redis."""
    try:
        # Используем json.dumps, так как Redis хранит строки
        redis_client.set(job_id, json.dumps(status_data), ex=3600) 
        print(f"📝 [Job: {job_id}] Статус обновлен: {status_data.get('status', 'N/A')}")
    except Exception as e:
        print(f"❌ [Job: {job_id}] Ошибка обновления статуса в Redis: {e}")

# ИЗМЕНЕНИЕ: Теперь фоновая задача принимает user_photo_data_uri
def run_face_swap_in_background(job_id: str, user_photo_data_uri: str):
    """Фоновая задача для обработки face-swap."""
    try:
        # ... (код подготовки данных и отправки запроса остается без изменений) ...
        # 1. Подготовка данных
        update_job_status(job_id, {"status": "preparing", "message": "Подготовка изображений"})
        target_image_uri = get_random_batyr_image_uri()
        headers = {"x-api-key": PIAPI_KEY, "Content-Type": "application/json"}
        payload = {
            "model": "Qubico/image-toolkit",
            "task_type": "face-swap",
            "input": {
                "target_image": target_image_uri,
                "swap_image": user_photo_data_uri,
            }
        }
        
        # 2. Запуск задачи в PiAPI
        update_job_status(job_id, {"status": "sending", "message": "Отправка запроса в PiAPI"})
        print(f"🚀 [Job: {job_id}] Отправка запроса в PiAPI...")
        with httpx.Client(timeout=30.0) as client:
            response = client.post("https://api.piapi.ai/api/v1/task", headers=headers, json=payload)
            response.raise_for_status()
            task_response = response.json()
        print(f"📋 [Job: {job_id}] Первичный ответ PiAPI: {task_response}")
        piapi_task_id = task_response.get("data", {}).get("task_id")
        if not piapi_task_id:
            raise ValueError(f"Не удалось получить task_id от PiAPI. Ответ: {task_response}")

        # 3. Опрос результата
        print(f"⏳ [Job: {job_id}] Начало опроса PiAPI для task_id: {piapi_task_id}")
        start_time = time.monotonic()
        
        while time.monotonic() - start_time < MAX_POLLING_TIME:
            try:
                with httpx.Client(timeout=15.0) as client:
                    res = client.get(f"https://api.piapi.ai/api/v1/task/{piapi_task_id}", headers=headers)
                
                if res.status_code == 200:
                    piapi_data = res.json().get("data", {})
                    
                    # ---> ГЛАВНОЕ ИСПРАВЛЕНИЕ ЗДЕСЬ <---
                    # Приводим статус к единому виду (Title Case), чтобы избежать проблем с регистром.
                    piapi_status = piapi_data.get("status", "Unknown").title() 
                    
                    print(f"📊 [Job: {job_id}] Статус PiAPI: {piapi_status} (обработано)")

                    if piapi_status == "Completed":
                        result_url = piapi_data.get("output", {}).get("image_url")
                        if not result_url:
                            raise ValueError("Статус 'Completed', но URL результата отсутствует в ответе PiAPI.")
                        update_job_status(job_id, {"status": "completed", "result_url": result_url})
                        print(f"✅ [Job: {job_id}] Задача успешно завершена.")
                        return
                        
                    elif piapi_status == "Failed":
                        error_details = piapi_data.get("error", {"message": "Неизвестная ошибка в PiAPI"})
                        update_job_status(job_id, {"status": "failed", "error": f"PiAPI ошибка: {error_details}"})
                        print(f"❌ [Job: {job_id}] PiAPI вернул ошибку: {error_details}")
                        return
                    
                    # Теперь 'processing' станет 'Processing' и эта проверка сработает
                    elif piapi_status in ["Processing", "Pending", "Staged"]:
                        # Все хорошо, ждем дальше
                        update_job_status(job_id, {"status": "processing", "piapi_status": piapi_status})
                        pass
                    else:
                        print(f"⚠️ [Job: {job_id}] Неизвестный статус от PiAPI: {piapi_status}. Прерывание опроса.")
                        update_job_status(job_id, {"status": "failed", "error": f"Неизвестный статус PiAPI: {piapi_status}"})
                        return

                else:
                    print(f"⚠️ [Job: {job_id}] Ошибка при опросе PiAPI: HTTP {res.status_code}")
            
            except httpx.RequestError as e:
                print(f"⏰ [Job: {job_id}] Ошибка сети при опросе PiAPI: {e}")
            
            time.sleep(POLLING_INTERVAL)

        timeout_msg = f"Превышено время ожидания ({MAX_POLLING_TIME}с). API не ответило вовремя."
        print(f"⏰ [Job: {job_id}] {timeout_msg}")
        update_job_status(job_id, {"status": "timeout", "error": timeout_msg})

    except Exception as e:
        error_msg = f"Критическая ошибка в фоновой задаче: {str(e)}"
        print(f"🔥 [Job: {job_id}] {error_msg}")
        traceback.print_exc()
        update_job_status(job_id, {"status": "failed", "error": error_msg})


@app.post("/api/start-face-swap", status_code=status.HTTP_202_ACCEPTED)
async def start_face_swap_task(
    background_tasks: BackgroundTasks, 
    user_photo: UploadFile = File(...)
):
    """Принимает фото, немедленно отвечает и запускает обработку в фоне."""
    job_id = str(uuid.uuid4())
    
    try:
        # Проверяем тип файла
        if not user_photo.content_type.startswith("image/"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Недопустимый тип файла. Пожалуйста, загрузите изображение (jpeg, png, webp)."
            )

        user_photo_bytes = await user_photo.read()
        
        # ИСПРАВЛЕНИЕ: Создаем полный Data URI для фото пользователя
        user_photo_base64 = base64.b64encode(user_photo_bytes).decode('utf-8')
        user_photo_data_uri = f"data:{user_photo.content_type};base64,{user_photo_base64}"
        
        # Создаем первоначальный статус в Redis
        initial_status = {"status": "accepted", "job_id": job_id}
        update_job_status(job_id, initial_status)

        # ИЗМЕНЕНИЕ: Передаем готовый URI в фоновую задачу
        background_tasks.add_task(run_face_swap_in_background, job_id, user_photo_data_uri)
        
        print(f"👍 [Job: {job_id}] Задача принята в работу.")
        return {"job_id": job_id, "status": "accepted", "message": "Задача принята в обработку. Проверяйте статус по job_id."}
        
    except Exception as e:
        print(f"❌ [Job: {job_id}] Ошибка при создании задачи: {e}")
        # Не используем job_id в ответе об ошибке, так как задача не была создана
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"Ошибка при запуске задачи: {str(e)}"
        )


@app.get("/api/task-status/{job_id}")
async def get_task_status(job_id: str):
    """Получить текущий статус задачи из Redis."""
    try:
        task_data_str = redis_client.get(job_id)
        if not task_data_str:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="Задача с таким ID не найдена или ее срок истек."
            )
        
        return json.loads(task_data_str)
        
    except Exception as e:
        print(f"❌ Ошибка получения статуса для {job_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Внутренняя ошибка сервера при получении статуса."
        )

# Другие эндпоинты (health, stats и т.д.) можно оставить без изменений.
# Они у тебя написаны хорошо.
# ...

@app.get("/api/health", summary="Проверка здоровья сервиса")
async def health_check():
    """Простая проверка работоспособности API и Redis"""
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