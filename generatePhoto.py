# Полностью замените содержимое файла main.py

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
import sqlite3

from PIL import Image
import io

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, status, BackgroundTasks, Header, Depends, Security, Request
from fastapi.security import APIKeyHeader
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import redis
from pydantic import BaseModel, Field

from database import init_db, get_or_create_user, can_user_generate, add_credits_to_user, get_total_users_count, get_db_connection
# FIX: Импортируем нашу новую функцию
from error_messages import get_error_message

load_dotenv()

# --- Конфигурация ---
PIAPI_KEY = os.getenv("PIAPI_API_KEY")
MALE_IMAGE_DIR = "/app/batyr-images"
FEMALE_IMAGE_DIR = "/app/batyrKyz-images"
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
MAX_POLLING_TIME = 120
POLLING_INTERVAL = 2
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PAYMENT_PROVIDER_TOKEN = os.getenv("TELEGRAM_PAYMENT_PROVIDER_TOKEN")
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL")
WEBHOOK_SECRET_TOKEN = os.getenv("WEBHOOK_SECRET_TOKEN")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

if not all([PIAPI_KEY, BOT_TOKEN, PAYMENT_PROVIDER_TOKEN, WEBHOOK_BASE_URL, WEBHOOK_SECRET_TOKEN]):
    raise RuntimeError("Одна или несколько критически важных переменных окружения отсутствуют! Проверьте .env файл.")

PRICES = {
    "1_gen": {"title": "1 генерация", "credits": 1, "price_amount": 10000},
    "5_gen": {"title": "Пакет на 5 генераций", "credits": 5, "price_amount": 45000},
    "10_gen": {"title": "Пакет на 10 генераций", "credits": 10, "price_amount": 80000},
}

try:
    redis_pool = redis.ConnectionPool(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
    redis_client = redis.Redis(connection_pool=redis_pool)
    redis_client.ping()
    print(f"✅ Подключено к Redis по адресу: {REDIS_HOST}:{REDIS_PORT}")
except redis.exceptions.ConnectionError as e:
    print(f"❌ Не удалось подключиться к Redis: {e}")
    redis_client = None

batyr_images_caches: Dict[str, List[Dict[str, str]]] = {"male": [], "female": []}

def _load_images_from_dir(directory_path: str) -> List[Dict[str, str]]:
    images = []
    if not os.path.exists(directory_path): return images
    print(f"⏳ Загрузка изображений из {directory_path}...")
    for filename in os.listdir(directory_path):
        if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
            try:
                with open(os.path.join(directory_path, filename), "rb") as f:
                    encoded = base64.b64encode(f.read()).decode('utf-8')
                    mime = f"image/{filename.split('.')[-1].lower().replace('jpg', 'jpeg')}"
                    images.append({"name": filename, "data_uri": f"data:{mime};base64,{encoded}"})
            except Exception as e:
                print(f"⚠️ Не удалось обработать файл {filename}: {e}")
    return images

def load_all_batyr_images_to_cache():
    batyr_images_caches["male"] = _load_images_from_dir(MALE_IMAGE_DIR)
    batyr_images_caches["female"] = _load_images_from_dir(FEMALE_IMAGE_DIR)
    print(f"✅ Кэшировано: {len(batyr_images_caches['male'])} мужских, {len(batyr_images_caches['female'])} женских образов.")

fastapi_kwargs = {"title": "Batyr AI API"}
if ENVIRONMENT == "production":
    fastapi_kwargs.update({"docs_url": None, "redoc_url": None})
app = FastAPI(**fastapi_kwargs)

async def set_telegram_webhook():
    webhook_url = f"{WEBHOOK_BASE_URL.strip('/')}/api/telegram-webhook"
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
            json={"url": webhook_url, "secret_token": WEBHOOK_SECRET_TOKEN, "allowed_updates": ["pre_checkout_query", "message"]}
        )
        if response.status_code == 200 and response.json().get("ok"):
            print(f"✅ Вебхук успешно установлен на: {webhook_url}")
        else:
            print(f"❌ ОШИБКА установки вебхука: {response.text}")

@app.on_event("startup")
async def on_startup():
    init_db()
    load_all_batyr_images_to_cache()
    if not redis_client: raise RuntimeError("Не удалось установить соединение с Redis.")
    await set_telegram_webhook()

origins = ["http://localhost:3000", "https://batyrai.com", "https://www.batyrai.com", "https://batyr-ai.vercel.app", "https://batyr-ai-madis-projects-f57aa02c.vercel.app"]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

telegram_init_data_header = APIKeyHeader(name="X-Telegram-Init-Data", auto_error=False)

# FIX: Модифицируем зависимость, чтобы она принимала язык
async def get_validated_telegram_data(
    init_data: str = Security(telegram_init_data_header),
    lang: str = Header("ru", alias="Accept-Language")
):
    if not init_data:
        raise HTTPException(status_code=401, detail=get_error_message("auth_header_missing", lang))
    try:
        unquoted_init_data = unquote(init_data)
        data_check_string, hash_from_telegram = [], ''
        for item in sorted(unquoted_init_data.split('&')):
            key, value = item.split('=', 1)
            if key == 'hash': hash_from_telegram = value
            else: data_check_string.append(f"{key}={value}")
        data_check_string = "\n".join(data_check_string)
        secret_key = hmac.new("WebAppData".encode(), BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if calculated_hash != hash_from_telegram:
            raise HTTPException(status_code=403, detail="Invalid data signature") # Внутренняя ошибка, не переводим
        user_data_dict = dict(kv.split('=') for kv in unquoted_init_data.split('&'))
        user_data = json.loads(user_data_dict.get('user', '{}'))
        user_id = user_data.get('id')
        if not user_id: raise ValueError("User ID not found")
        get_or_create_user(user_id=user_id, username=user_data.get('username', ''), first_name=user_data.get('first_name', ''))
        return user_data
    except Exception as e:
        print(f"🔥 Ошибка валидации Telegram initData: {e}")
        raise HTTPException(status_code=403, detail=get_error_message("auth_validation_failed", lang))

class PhotoSendRequest(BaseModel): imageUrl: str
class CreateInvoiceRequest(BaseModel): package_id: str
class TGUser(BaseModel): id: int
class PreCheckoutQuery(BaseModel): id: str; from_user: TGUser = Field(..., alias="from"); invoice_payload: str
class SuccessfulPayment(BaseModel): invoice_payload: str
class TGMessage(BaseModel): chat: TGUser; successful_payment: SuccessfulPayment
class Update(BaseModel): update_id: int; pre_checkout_query: Optional[PreCheckoutQuery] = None; message: Optional[TGMessage] = None

def get_random_batyr_image_uri(gender: str = "male"):
    cache_key = gender if gender in batyr_images_caches and batyr_images_caches[gender] else "male"
    image_cache = batyr_images_caches.get(cache_key) or batyr_images_caches.get("male", [])
    if not image_cache: raise ValueError("Кэш изображений пуст.")
    return random.choice(image_cache)['data_uri']

def update_job_status(job_id: str, status_data: dict):
    try:
        redis_client.set(job_id, json.dumps(status_data), ex=3600)
    except Exception as e:
        print(f"❌ [Job: {job_id}] Ошибка обновления статуса в Redis: {e}")

def resize_image_to_base64(image_bytes: bytes, max_size: int = 1024) -> str:
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode in ("RGBA", "P"): img = img.convert("RGB")
        img.thumbnail((max_size, max_size))
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        encoded_string = base64.b64encode(buffer.getvalue()).decode('utf-8')
        return f"data:image/jpeg;base64,{encoded_string}"
    except Exception as e:
        raise ValueError(f"Не удалось обработать изображение: {e}")

async def send_telegram_message(user_id: int, text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = { "chat_id": user_id, "text": text, "parse_mode": "HTML" }
    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, json=payload)
    except Exception as e:
        print(f"🔥 Не удалось отправить сообщение пользователю {user_id}: {e}")

def run_face_swap_in_background(job_id: str, user_photo_bytes: bytes, user_id: int, gender: str, lang: str):
    try:
        update_job_status(job_id, {"status": "processing", "message": "⏳ Уменьшаю ваше фото и подбираю образ..."})
        user_photo_data_uri = resize_image_to_base64(user_photo_bytes)
        target_image_uri = get_random_batyr_image_uri(gender)
        headers = {"x-api-key": PIAPI_KEY, "Content-Type": "application/json"}
        payload = { "model": "Qubico/image-toolkit", "task_type": "face-swap", "input": {"target_image": target_image_uri, "swap_image": user_photo_data_uri} }
        update_job_status(job_id, {"status": "sending", "message": "🛰️ Отправляю данные в нейросеть..."})
        
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
                    update_job_status(job_id, {"status": "completed", "result_url": result_url, "message": "✅ Изображение готово"})
                    asyncio.run(send_telegram_message(user_id, "<b>Ваш портрет батыра готов!</b>\n\nВозвращайтесь в приложение, чтобы скачать его."))
                    return
                elif piapi_status == "Failed":
                    error_details = piapi_data.get("error", "unknown piapi error").lower()
                    error_key = "face_not_found" if "face not found" in error_details else "generation_failed_generic"
                    user_message = get_error_message(error_key, lang)
                    update_job_status(job_id, {"status": "failed", "error": user_message})
                    return
                elif piapi_status in ["Processing", "Pending", "Staged"]:
                    update_job_status(job_id, {"status": "processing", "message": f"👨‍🎨 Нейросеть рисует... (статус: {piapi_status})"})
                else:
                    update_job_status(job_id, {"status": "failed", "error": f"Неизвестный статус PiAPI: {piapi_status}"})
                    return

        update_job_status(job_id, {"status": "failed", "error": get_error_message("timeout_error", lang)})
    except Exception as e:
        error_msg = get_error_message("generation_failed_generic", lang)
        traceback.print_exc()
        update_job_status(job_id, {"status": "failed", "error": error_msg})


@app.post("/api/start-face-swap", status_code=status.HTTP_202_ACCEPTED)
async def start_face_swap_task(
    background_tasks: BackgroundTasks,
    user_photo: UploadFile = File(...),
    gender: str = Form("male"),
    # FIX: Получаем язык из заголовка
    lang: str = Header("ru", alias="Accept-Language"),
    validated_user: dict = Depends(get_validated_telegram_data)
):
    user_id = validated_user.get('id')
    can_gen, _, remaining_attempts = can_user_generate(user_id=user_id)
    if not can_gen:
        # FIX: Используем переведенное сообщение
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=get_error_message("payment_required", lang))

    job_id = str(uuid.uuid4())
    if not user_photo.content_type or not user_photo.content_type.startswith("image/"):
        # FIX: Используем переведенное сообщение
        raise HTTPException(status_code=400, detail=get_error_message("invalid_file_type", lang))

    user_photo_bytes = await user_photo.read()
    update_job_status(job_id, {"status": "accepted", "job_id": job_id, "message": "⏳ Принято в очередь..."})
    # FIX: Передаем язык в фоновую задачу
    background_tasks.add_task(run_face_swap_in_background, job_id, user_photo_bytes, user_id, gender, lang)

    print(f"👍 [Job: {job_id}] Задача принята для {user_id}. Осталось кредитов: {remaining_attempts}.")
    return {"job_id": job_id, "status": "accepted", "message": "Задача принята в обработку.", "remaining_attempts": remaining_attempts}

@app.post("/api/create-invoice", dependencies=[Depends(get_validated_telegram_data)])
async def create_invoice(request: CreateInvoiceRequest):
    package_id = request.package_id
    if package_id not in PRICES:
        raise HTTPException(status_code=404, detail="Выбранный пакет не найден.")
    package = PRICES[package_id]
    payload = {"title": package["title"], "description": f"Пополнение баланса на {package['credits']} генераций.", "payload": package_id, "provider_token": PAYMENT_PROVIDER_TOKEN, "currency": "KZT", "prices": [{"label": package["title"], "amount": package["price_amount"]}], "start_parameter": "batyrai-payment"}
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/createInvoiceLink", json=payload)
            response.raise_for_status()
            result = response.json()
            if result.get("ok"):
                return {"invoice_link": result["result"]}
            else:
                raise HTTPException(status_code=500, detail=f"Ошибка API Telegram: {result.get('description')}")
    except httpx.HTTPStatusError as e:
        print(f"🔥 Ошибка создания счета: {e.response.text}")
        raise HTTPException(status_code=500, detail="Не удалось создать счет на оплату.")

@app.post("/api/telegram-webhook")
async def telegram_webhook(request: Request, x_telegram_bot_api_secret_token: str = Header(None)):
    if x_telegram_bot_api_secret_token != WEBHOOK_SECRET_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        data = await request.json()
        update = Update.model_validate(data)
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid data"})

    if update.pre_checkout_query:
        query = update.pre_checkout_query
        ok = query.invoice_payload in PRICES
        error_message = None if ok else "Товар больше не доступен."
        async with httpx.AsyncClient() as client:
            await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/answerPreCheckoutQuery", json={"pre_checkout_query_id": query.id, "ok": ok, "error_message": error_message})
        print(f"✅ PreCheckout для {query.from_user.id} {'подтвержден' if ok else 'отклонен'}.")
        return JSONResponse({"ok": True})

    if update.message and update.message.successful_payment:
        payment = update.message.successful_payment
        user_id = update.message.chat.id
        package_id = payment.invoice_payload
        if package_id in PRICES:
            credits_to_add = PRICES[package_id]["credits"]
            new_balance = add_credits_to_user(user_id=user_id, amount=credits_to_add)
            success_text = (f"<b>Оплата прошла успешно!</b> ✨\n\n"
                            f"Вам начислено: <b>{credits_to_add} генераций</b>.\n"
                            f"Ваш новый баланс: <b>{new_balance} генераций</b>.\n\n"
                            f"Возвращайтесь в приложение и продолжайте творить!")
            await send_telegram_message(user_id, success_text)
        return JSONResponse({"ok": True})

    return JSONResponse({"ok": True})

@app.get("/api/task-status/{job_id}", dependencies=[Depends(get_validated_telegram_data)])
async def get_task_status(job_id: str, lang: str = Header("ru", alias="Accept-Language")):
    task_data_str = redis_client.get(job_id)
    if not task_data_str:
        raise HTTPException(status_code=404, detail=get_error_message("task_not_found", lang))
    return json.loads(task_data_str)

@app.post("/api/send-photo-to-chat", dependencies=[Depends(get_validated_telegram_data)])
async def send_photo_to_chat(
    request: PhotoSendRequest,
    lang: str = Header("ru", alias="Accept-Language"),
    validated_user: dict = Depends(get_validated_telegram_data)
):
    user_id = validated_user.get('id')
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    payload = { "chat_id": user_id, "photo": request.imageUrl, "caption": "Ваш портрет Батыра готов! ✨\n\nСоздано в @BatyrAI_bot" }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=30.0)
            response.raise_for_status()
        return {"status": "ok", "message": "Фото успешно отправлено в ваш чат."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{get_error_message('photo_send_failed', lang)}: {e}")

@app.get("/api/download-image", dependencies=[Depends(get_validated_telegram_data)])
async def download_image_proxy(url: str):
    if not url: raise HTTPException(status_code=400, detail="URL не указан.")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, follow_redirects=True, timeout=30.0)
            response.raise_for_status()
            return StreamingResponse(response.iter_bytes(), media_type=response.headers.get('content-type'))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при скачивании файла: {e}")

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
    except Exception: pass
    return {"status": "healthy", "redis": redis_status, "male_images_cached": len(batyr_images_caches.get("male", [])), "female_images_cached": len(batyr_images_caches.get("female", [])), "timestamp": datetime.now().isoformat()}

@app.get("/api/user/status", dependencies=[Depends(get_validated_telegram_data)])
async def get_user_status(validated_user: dict = Depends(get_validated_telegram_data)):
    user_id = validated_user.get('id')
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT generation_credits FROM users WHERE user_id = ?", (user_id,))
        user_data = cursor.fetchone()
        
        if user_data:
            return {"credits": user_data['generation_credits']}
        else:
            return {"credits": 0}
            
    except Exception as e:
        print(f"🔥 Ошибка получения статуса пользователя {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Не удалось получить данные пользователя.")
    finally:
        if conn:
            conn.close()