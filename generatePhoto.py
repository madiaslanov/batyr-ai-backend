import os
import httpx
import base64
import traceback
import random
from fastapi import FastAPI, HTTPException, UploadFile, File, status
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

# --- Конфигурация ---
PIAPI_KEY = os.getenv("PIAPI_API_KEY")

if not PIAPI_KEY:
    raise RuntimeError("Не найден PIAPI_API_KEY в .env файле")

IMAGE_DIR = "/app/batyr-images"

# --- Приложение FastAPI ---
app = FastAPI(
    title="Batyr AI API",
    description="API для замены лиц на изображениях батыров."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Вспомогательная функция ---
def get_random_batyr_image_base64():
    """
    Находит все изображения в папке IMAGE_DIR, выбирает случайное,
    читает его и кодирует в строку Base64.
    """
    try:
        available_images = [f for f in os.listdir(IMAGE_DIR) if os.path.isfile(os.path.join(IMAGE_DIR, f))]
        
        if not available_images:
            print(f"🔥 ОШИБКА: Не найдено изображений в директории: {IMAGE_DIR}")
            raise Exception("На сервере не найдены предварительно сгенерированные изображения.")
        
        random_image_name = random.choice(available_images)
        image_path = os.path.join(IMAGE_DIR, random_image_name)
        
        print(f"🖼️  Выбрано случайное изображение: {image_path}")

        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
            
    except Exception as e:
        print(f"🔥 Ошибка при получении случайного изображения: {e}")
        traceback.print_exc()
        raise

# --- Эндпоинты API ---

@app.post("/api/piapi/face-swap", summary="Запустить задачу замены лица")
async def create_face_swap_task(user_photo: UploadFile = File(..., description="Фото пользователя для замены лица")):
    """
    Принимает изображение пользователя, выбирает случайное изображение батыра
    и создает задачу на замену лица в PiAPI.
    """
    try:
        print("⏳ Чтение загруженного изображения пользователя...")
        user_image_bytes = await user_photo.read()
        user_image_base64 = base64.b64encode(user_image_bytes).decode('utf-8')

        print("🎨 Получение готового изображения батыра...")
        batyr_image_base64 = get_random_batyr_image_base64()
        print("✅ Изображение батыра получено.")

        headers = {
            "x-api-key": PIAPI_KEY,
            "Content-Type": "application/json"
        }

        payload = {
            "model": "Qubico/image-toolkit",
            "task_type": "multi-face-swap",
            "input": {
                "swap_image": user_image_base64,  # Это изображение, откуда берем лицо (пользовательское)
                "target_image": batyr_image_base64, # Это изображение, куда вставляем лицо (батыр)
                "swap_faces_index": "0", # Предполагаем, что лицо на user_photo всегда первое
                "target_faces_index": "0" # Предполагаем, что лицо на batyr_photo всегда первое
            }
        }

        print("🚀 Отправка запроса на замену лица в PiAPI...")
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post("https://api.piapi.ai/api/v1/task", headers=headers, json=payload)

        print(f"📤 Ответ от PiAPI: {response.text}")
        response.raise_for_status()

        return response.json()

    except httpx.HTTPStatusError as e:
        print(f"🔥 Ошибка HTTP от PiAPI: {e.response.status_code} - {e.response.text}")
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Ошибка от внешнего сервиса: {e.response.text}"
        )
    except httpx.RequestError as e:
        print(f"🔥 Ошибка при запросе к PiAPI (сетевая или таймаут): {e}")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT, # Или 503 Service Unavailable
            detail=f"Не удалось связаться с внешним сервисом: {str(e)}"
        )
    except Exception as e:
        print(f"🔥 Исключение в эндпоинте face-swap: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Внутренняя ошибка сервера: {str(e)}")


@app.get("/api/piapi/task/{task_id}", summary="Получить результат задачи")
async def get_task_result(task_id: str):
    """
    Проверяет статус задачи по ее ID в PiAPI.
    """
    headers = { "x-api-key": PIAPI_KEY }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"https://api.piapi.ai/api/v1/task/{task_id}", headers=headers)
        
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        print(f"🔥 Ошибка HTTP от PiAPI при получении статуса: {e.response.status_code} - {e.response.text}")
        if e.response.status_code == status.HTTP_404_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Задача с ID {task_id} не найдена или уже не существует."
            )
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Ошибка от внешнего сервиса при проверке статуса: {e.response.text}"
        )
    except httpx.RequestError as e:
        print(f"🔥 Ошибка при запросе к PiAPI (сетевая или таймаут) при получении статуса: {e}")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Не удалось связаться с внешним сервисом для проверки статуса: {str(e)}"
        )
    except Exception as e:
        print(f"🔥 Исключение в эндпоинте get-task-result: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Внутренняя ошибка сервера: {str(e)}")