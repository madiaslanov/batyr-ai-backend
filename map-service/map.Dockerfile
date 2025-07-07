# Используем официальный образ Python
FROM python:3.9-slim

# ✅↓↓↓ ДОБАВЛЕННЫЙ БЛОК ↓↓↓✅
# Устанавливаем системные зависимости, включая FFmpeg для pydub
# После установки чистим кэш, чтобы уменьшить размер итогового образа
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Устанавливаем рабочую директорию в контейнере
WORKDIR /app

# Копируем файл с зависимостями
COPY map.requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r map.requirements.txt

# Копируем код приложения и файл с данными в контейнер
COPY mapBatyr.py .
COPY batyrs_data.json .

# Указываем команду для запуска приложения (ваша команда сохранена)
# Флаг -u отключает буферизацию вывода, что полезно для просмотра логов в реальном времени
CMD ["python", "-u", "mapBatyr.py"]