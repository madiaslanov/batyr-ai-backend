# assistant.Dockerfile - ИСПРАВЛЕННЫЙ ВАРИАНТ

FROM python:3.10-slim

# Устанавливаем ffmpeg для конвертации аудио
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Сначала копируем файл с зависимостями. Это лучший подход для кеширования Docker.
COPY assistant.requirements.txt .
RUN pip install --no-cache-dir -r assistant.requirements.txt

# --- ГЛАВНОЕ ИЗМЕНЕНИЕ ---
# Копируем ВСЕ файлы из текущей папки (включая database.py) в контейнер.
COPY . .

# Команда для запуска вашего приложения (добавил --reload для удобства разработки)
CMD ["uvicorn", "assistant:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]