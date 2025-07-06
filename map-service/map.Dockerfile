# Используем официальный образ Python
FROM python:3.9-slim

# Устанавливаем рабочую директорию в контейнере
WORKDIR /app

# Копируем файл с зависимостями
COPY map.requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r map.requirements.txt

# Копируем код приложения и файл с данными в контейнер
COPY mapbatyr.py .
COPY batyrs_data.json .

# Указываем команду для запуска приложения
CMD ["python", "-u", "mapbatyr.py"]