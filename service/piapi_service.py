import aiohttp
from pathlib import Path

PIAPI_KEY = "your_piapi_key_here"

async def swap_faces(user_photo: Path, images: list[Path], task_id: str) -> list[str]:
    swapped_paths = []

    async with aiohttp.ClientSession() as session:
        for i, img_path in enumerate(images):
            with open(user_photo, "rb") as user_file, open(img_path, "rb") as gen_file:
                data = aiohttp.FormData()
                data.add_field("swap_image", user_file, filename="user.jpg", content_type="image/jpeg")
                data.add_field("target_image", gen_file, filename="target.png", content_type="image/png")

                headers = {"Authorization": f"Bearer {PIAPI_KEY}"}
                async with session.post("https://api.piapi.ai/swapface", data=data, headers=headers) as resp:
                    result = await resp.read()

                    output_path = img_path.parent / f"swapped_{i}.png"
                    with open(output_path, "wb") as f:
                        f.write(result)

                    swapped_paths.append(str(output_path))

    return swapped_paths
