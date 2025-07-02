FROM python:3.10-slim

WORKDIR /app

# Устанавливаем системные зависимости (если нужно TTS/audio для speechkit)
RUN apt-get update && apt-get install -y ffmpeg gcc && rm -rf /var/lib/apt/lists/*

COPY . .

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 80

# Правильный CMD для вашего проекта
CMD ["uvicorn", "generatePhoto:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
