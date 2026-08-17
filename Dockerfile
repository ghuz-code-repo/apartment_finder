# syntax=docker/dockerfile:1
# Директива выше включает BuildKit-синтаксис: без неё не работает
# --mount=type=cache в слое установки зависимостей.

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

# Тяжёлые зависимости ставим ПЕРВЫМИ и отдельным слоем. auth-connector
# меняется часто, requirements.txt — почти никогда; при обратном порядке
# любая правка auth-connector сбрасывала кэш и тянула переустановку ~70
# пакетов (scipy, numpy, pandas, scikit-learn, matplotlib, lxml).
COPY apartment_finder/requirements.txt .

# Кэш колёс переживает пересборки, поэтому --no-cache-dir здесь не нужен:
# он бы отключил ровно тот кэш, который мы монтируем.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# auth-connector — общий пакет из соседнего каталога, ставится после тяжёлого
# слоя. --force-reinstall обязателен: версия пакета меняется не каждый раз,
# и pip иначе счёл бы уже установленную достаточной.
COPY auth-connector /tmp/auth-connector
RUN pip install --no-cache-dir --force-reinstall /tmp/auth-connector && rm -rf /tmp/auth-connector

# Ломать сборку, а не рантайм. Код сервиса требует auth-connector 2.x
# (модуль permission_utils, UserContext без is_admin). Со старым пакетом
# приложение импортировалось бы до первого запроса и падало воркером —
# сервис отдавал 502 целиком. Обычно означает, что сабмодуль auth-connector
# остался на прежнем коммите: git -C auth-connector checkout master && git pull
RUN python -c "import auth_connector as a, sys; v = a.__version__; sys.exit(0 if int(v.split('.')[0]) >= 2 else 'auth-connector %s < 2.0.0 — обновите сабмодуль auth-connector' % v)"

# Копируем весь код приложения
COPY apartment_finder/ .

# Создаем директории для данных
RUN mkdir -p /app/instance /app/uploads

# Устанавливаем переменные окружения
ENV FLASK_APP=app_with_auth_connector.py
ENV FLASK_ENV=production
ENV PYTHONPATH=/app
# Без этого print() из app_with_auth_connector.py оседает в буфере stdout:
# в контейнере stdout — пайп, а не терминал, поэтому Python буферизует его
# блоками по ~8 КБ. Стартовых строк на такой объём не набирается, и логи
# регистрации сервиса не доходили ни до docker logs, ни до Dozzle, хотя
# строки самого gunicorn были видны — он пишет через logging, а тот флашит.
ENV PYTHONUNBUFFERED=1

# Открываем порт
EXPOSE 80

# Команда запуска через gunicorn.
# gthread вместо sync: с двумя sync-воркерами приложение обрабатывало
# ровно два запроса разом, и пачка тайлов при зуме блокировала всё
# остальное. Раздача тайлов упирается в I/O, потоки её и разгружают.
CMD ["gunicorn", "--bind", "0.0.0.0:80", \
     "--worker-class", "gthread", "--workers", "2", "--threads", "8", \
     "--timeout", "120", "app_with_auth_connector:app"]
