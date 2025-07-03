# assistant.Dockerfile
FROM python:3.10-slim

WORKDIR /app

# Копируем только те файлы, которые нужны ассистенту
COPY assistant.py .
COPY assistant.requirements.txt .
COPY .env .

RUN pip install --no-cache-dir -r assistant.requirements.txt

# Запускаем Uvicorn на порту 8001
CMD ["uvicorn", "assistant:app", "--host", "0.0.0.0", "--port", "8001"]