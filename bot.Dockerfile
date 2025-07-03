# Используем тот же базовый образ Python
FROM python:3.10-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем только те файлы, которые нужны боту
COPY bot.py .
COPY bot.requirements.txt .
COPY .env .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r bot.requirements.txt

# Команда для запуска бота при старте контейнера
CMD ["python", "bot.py"]