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
RUN pip install --no-cache-dir --force-reinstall /tmp/auth-connector && rm -rf /tmp/auth-connector

# Ломать сборку, а не рантайм. Код сервиса требует auth-connector 2.x
# (модуль permission_utils, UserContext без is_admin). Со старым пакетом
# приложение импортировалось бы до первого запроса и падало воркером —
# сервис отдавал 502 целиком. Обычно означает, что сабмодуль auth-connector
# остался на прежнем коммите: git -C auth-connector checkout master && git pull
RUN python -c "import auth_connector as a, sys; v = a.__version__; sys.exit(0 if int(v.split('.')[0]) >= 2 else 'auth-connector %s < 2.0.0 — обновите сабмодуль auth-connector' % v)"

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

# Команда запуска через gunicorn.
# gthread вместо sync: с двумя sync-воркерами приложение обрабатывало
# ровно два запроса разом, и пачка тайлов при зуме блокировала всё
# остальное. Раздача тайлов упирается в I/O, потоки её и разгружают.
CMD ["gunicorn", "--bind", "0.0.0.0:80", \
     "--worker-class", "gthread", "--workers", "2", "--threads", "8", \
     "--timeout", "120", "app_with_auth_connector:app"]
