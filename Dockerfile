# Используем официальный образ Python
FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Set timezone
ENV TZ=Asia/Tashkent

# Copy and install auth-connector first
COPY auth-connector /tmp/auth-connector
RUN pip install --no-cache-dir /tmp/auth-connector && rm -rf /tmp/auth-connector

# Копируем файл с зависимостями
COPY apartment_finder/requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код приложения
COPY apartment_finder/ .

# Создаем директории для данных
RUN mkdir -p /app/instance /app/uploads

# Устанавливаем переменные окружения
ENV FLASK_APP=app_with_auth_connector.py
ENV FLASK_ENV=production
ENV PYTHONPATH=/app

# Открываем порт
EXPOSE 80

# Команда запуска через gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:80", "--workers", "2", "--timeout", "120", "app_with_auth_connector:app"]
