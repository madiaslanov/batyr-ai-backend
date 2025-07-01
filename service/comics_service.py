from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

RESULTS_DIR = Path("storage/results")

async def create_comic(images: list[str], script: str, task_id: str) -> str:
    loaded_images = [Image.open(img_path) for img_path in images]

    width = max(img.width for img in loaded_images)
    height = sum(img.height for img in loaded_images)
    comic = Image.new("RGB", (width, height), "white")

    y = 0
    for img in loaded_images:
        comic.paste(img, (0, y))
        y += img.height

    draw = ImageDraw.Draw(comic)
    font = ImageFont.load_default()
    draw.text((10, 10), script, font=font, fill="black")

    output_path = RESULTS_DIR / f"{task_id}_comic.png"
    comic.save(output_path)

    return str(output_path)
