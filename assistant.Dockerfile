# assistant.Dockerfile

FROM python:3.10-slim

# ✅ Устанавливаем ffmpeg для конвертации аудио
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY assistant.py .
COPY assistant.requirements.txt .
COPY .env .

RUN pip install --no-cache-dir -r assistant.requirements.txt

# Команда для запуска вашего приложения
CMD ["uvicorn", "assistant:app", "--host", "0.0.0.0", "--port", "8001"]