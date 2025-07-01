import aiohttp
import os
from pathlib import Path
import base64

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
UPLOADS_DIR = Path("storage/uploads")

async def generate_dalle_images(task_id: str) -> list[Path]:
    prompts = [
        "sci-fi hero flying through sky",
        "cyberpunk battle in neon city",
        "futuristic villain chasing protagonist"
    ]
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    dalle_paths = []

    async with aiohttp.ClientSession() as session:
        for i, prompt in enumerate(prompts):
            async with session.post(
                "https://api.openai.com/v1/images/generations",
                headers=headers,
                json={
                    "model": "dall-e-3",
                    "prompt": prompt,
                    "n": 1,
                    "size": "1024x1024"
                },
            ) as resp:
                data = await resp.json()
                img_url = data["data"][0]["url"]
                img_data = await session.get(img_url)
                img_bytes = await img_data.read()

                path = UPLOADS_DIR / task_id / f"dalle_{i}.png"
                with open(path, "wb") as f:
                    f.write(img_bytes)
                dalle_paths.append(path)

    return dalle_paths
