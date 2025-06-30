import os
import httpx
import base64
import traceback
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

PIAPI_KEY = os.getenv("PIAPI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not PIAPI_KEY or not OPENAI_API_KEY:
    raise RuntimeError("Missing API keys in .env")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === POST: face-swap ===
@app.post("/api/piapi/face-swap")
async def create_face_swap_task(target_image: UploadFile = File(...)):
    try:
        print("⏳ Reading uploaded image...")
        user_image_bytes = await target_image.read()
        user_image_base64 = base64.b64encode(user_image_bytes).decode()

        print("🎨 Generating batyr image with DALL-E...")
        dalle_image_url = await generate_batyr_image_url()
        print("✅ Batyr image URL:", dalle_image_url)

        headers = {
            "x-api-key": PIAPI_KEY,
            "Content-Type": "application/json"
        }

        payload = {
            "model": "Qubico/image-toolkit",
            "task_type": "multi-face-swap",
            "input": {
                "swap_image": dalle_image_url,
                "target_image": user_image_base64,
                "swap_faces_index": "0",
                "target_faces_index": "0"
            }
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.piapi.ai/api/v1/task",
                headers=headers,
                json=payload
            )

        print("📤 PiAPI response:", response.text)
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail=f"PiAPI error: {response.text}")

        data = response.json()

        # ✅ Проверяем наличие готового изображения
        output = data["data"].get("output")
        if output and output.get("image_url"):
            return data
        elif "task_id" in data["data"]:
            return data
        else:
            raise HTTPException(status_code=500, detail="❌ Ни task_id, ни output не получены")

    except Exception as e:
        print("🔥 Exception:", str(e))
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

# === GET: task result ===
@app.get("/api/piapi/task/{task_id}")
async def get_task_result(task_id: str):
    headers = {
        "x-api-key": PIAPI_KEY
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"https://api.piapi.ai/api/v1/task/{task_id}", headers=headers)

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    return response.json()

# === DALL·E генерация изображения ===
async def generate_batyr_image_url():
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "dall-e-3",
        "prompt": (
    "A realistic portrait of a Kazakh batyr (warrior) on horseback, facing the viewer directly. "
    "He is wearing traditional Kazakh armor made of leather and metal, with a fur-lined coat and a feathered helmet. "
    "His face is clearly visible, with a well-groomed beard and absolutely no mustache. "
    "He has long dark hair, sharp symmetrical facial features, and is looking straight into the camera with a calm and proud expression. "
    "The scene is set in the vast Kazakh steppe with distant mountains and a dramatic sky. "
    "He is seated proudly on a powerful horse, with the steppe wind blowing through his hair. "
    "Cinematic lighting, hyper-realistic style, ultra-detailed textures, sharp focus, 4K resolution. "
    "Perfectly centered for face-swap without obstructions or facial accessories."
),

        "n": 1,
        "size": "1024x1024"
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/images/generations",
            headers=headers,
            json=payload
        )

    if response.status_code != 200:
        raise Exception(f"OpenAI error: {response.text}")

    data = response.json()
    return data["data"][0]["url"]
