from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from uuid import uuid4
from services.dalle_service import generate_dalle_images
from services.piapi_service import swap_faces
from services.comics_service import create_comic
from pathlib import Path
import shutil
import os

app = FastAPI()

TASKS = {}

UPLOADS_DIR = Path("storage/uploads")
RESULTS_DIR = Path("storage/results")
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

@app.post("/api/comics/init")
async def init_comics(file: UploadFile = File(...)):
    task_id = str(uuid4())
    user_path = UPLOADS_DIR / task_id
    user_path.mkdir(parents=True, exist_ok=True)

    photo_path = user_path / "user.jpg"
    with open(photo_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # 1. Генерация 3 изображений
    dalle_images = await generate_dalle_images(task_id)

    # 2. Swapface
    swapped_paths = await swap_faces(photo_path, dalle_images, task_id)

    # Сохраняем задачу
    TASKS[task_id] = {
        "status": "ready",
        "images": swapped_paths,
        "script": None,
        "comic_path": None,
    }

    return {"task_id": task_id}

@app.get("/api/comics/status/{task_id}")
async def get_task_status(task_id: str):
    task = TASKS.get(task_id)
    if not task:
        return JSONResponse(status_code=404, content={"error": "Task not found"})

    return {
        "status": task["status"],
        "images": task["images"],
    }

@app.post("/api/comics/plot")
async def generate_comic(task_id: str = Form(...), script: str = Form(...)):
    task = TASKS.get(task_id)
    if not task:
        return JSONResponse(status_code=404, content={"error": "Task not found"})

    comic_path = await create_comic(task["images"], script, task_id)
    task["comic_path"] = comic_path
    task["status"] = "done"

    return {"comic_url": f"/api/comics/result/{task_id}"}

@app.get("/api/comics/result/{task_id}")
async def get_comic(task_id: str):
    task = TASKS.get(task_id)
    if not task or not task["comic_path"]:
        return JSONResponse(status_code=404, content={"error": "Comic not ready"})

    return FileResponse(task["comic_path"], media_type="image/png")
