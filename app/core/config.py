# app/core/config.py

import os

try:
    from dotenv import load_dotenv
    load_dotenv(encoding='utf-8')
except Exception:
    pass


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'a-very-secret-key')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Корень загруженных файлов. Namely НЕ внутри static: nginx отдаёт
    # {prefix}/static/ отдельным блоком без auth_request, поэтому всё, что
    # лежало там, скачивалось без авторизации. Каталог совпадает с томом
    # ./uploads:/app/uploads из docker-compose — заодно загрузки перестают
    # пропадать при пересборке образа.
    UPLOAD_ROOT = os.environ.get('UPLOAD_ROOT') or os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', '..', 'uploads')
    )
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHANNEL_ID = int(os.environ.get('TELEGRAM_CHANNEL_ID', '0'))
    SOURCE_MYSQL_URI = os.environ.get('SOURCE_MYSQL_URI', '')

    # Email отправляется через централизованный notification-service.
    # Здесь храним только список получателей (поддерживается list или CSV-строка через env).
    _mail_recipients_env = os.environ.get('MAIL_RECIPIENTS')
    MAIL_RECIPIENTS = (
        [r.strip() for r in _mail_recipients_env.split(',') if r.strip()]
        if _mail_recipients_env
        else ['d.plakhotnyi@gh.uz']
    )
    NOTIFICATION_SERVICE_URL = os.environ.get(
        'NOTIFICATION_SERVICE_URL', 'http://notification-service:80'
    )
    USD_TO_UZS_RATE = 13050.0

    # Ссылка на сделку в CRM для вкладки «Моя дебиторка».
    # {deal_id} подставляется из данных; пустое значение просто убирает ссылки.
    CRM_DEAL_URL = os.environ.get('CRM_DEAL_URL', '')

    # Бот-напоминалка о дебиторке. Логин нужен для ссылки-приглашения,
    # час — время ежедневной рассылки по времени сервера.
    TELEGRAM_BOT_USERNAME = os.environ.get('TELEGRAM_BOT_USERNAME', '')
    TELEGRAM_REMINDER_HOUR = int(os.environ.get('TELEGRAM_REMINDER_HOUR', '9'))

    # --- Macro API v2 (планировки квартир) ---
    # Базовый адрес заканчивается версией: https://<ваш-сервер>/v2
    MACRO_API_URL = os.environ.get('MACRO_API_URL', '')
    MACRO_API_TOKEN = os.environ.get('MACRO_API_TOKEN', '')
    # Файлы планировок приходят относительными путями (/upload/estate/plan_1.jpg),
    # здесь — хост, к которому их достраивать.
    MACRO_FILES_BASE_URL = os.environ.get('MACRO_FILES_BASE_URL', '')
    # Дополнительные хосты хранилища через запятую, если файлы отдаёт CDN.
    MACRO_FILES_ALLOWED_HOSTS = os.environ.get('MACRO_FILES_ALLOWED_HOSTS', '')
    # Проверка TLS-сертификата Macro: true (по умолчанию) — обычная проверка,
    # путь — свой CA-бандл, false — проверка отключена. Отключать только для
    # внутреннего адреса: сервер в изолированной сети не может продлить
    # Let's Encrypt-сертификат, и он там протухший.
    MACRO_API_VERIFY_SSL = os.environ.get('MACRO_API_VERIFY_SSL', 'true')

    # До какого зума карта запрашивает тайлы у сервера. Глубже Leaflet
    # растягивает последний доступный уровень: каждый следующий зум
    # учетверяет число тайлов, а на глаз разница уже невелика.
    TILE_MAX_NATIVE_ZOOM = int(os.environ.get('TILE_MAX_NATIVE_ZOOM', '17'))

    # С какого зума отметки перестают группироваться в кластеры. Ниже этого
    # уровня на карте лежат сотни DOM-элементов, и зум начинает подвисать.
    MAP_DISABLE_CLUSTERING_AT_ZOOM = int(
        os.environ.get('MAP_DISABLE_CLUSTERING_AT_ZOOM', '16'))

    # Если задан, выгрузку пакета региона берёт на себя nginx: приложение
    # отвечает одним заголовком и сразу освобождает поток, а файл уходит
    # в сокет средствами ядра. Требует internal-location в конфиге nginx.
    TILES_XACCEL_PREFIX = os.environ.get('TILES_XACCEL_PREFIX', '')


# --- ИЗМЕНЕНИЯ НУЖНО ВНЕСТИ ЗДЕСЬ ---
class DevelopmentConfig(Config):
    DEBUG = True

    # Основная база данных (абсолютный путь в instance/)
    _basedir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    _instance_path = os.path.join(_basedir, 'instance')

    SQLALCHEMY_DATABASE_URI = os.environ.get('MAIN_DATABASE_URL') or \
        'sqlite:///' + os.path.join(_instance_path, 'main_app.db')

    # Оставляем 'planning_db' и добавляем 'mysql_source'
    SQLALCHEMY_BINDS = {
        'planning_db': os.environ.get('PLANNING_DATABASE_URL') or \
            'sqlite:///' + os.path.join(_instance_path, 'planning.db'),
    }
    if Config.SOURCE_MYSQL_URI:
        SQLALCHEMY_BINDS['mysql_source'] = Config.SOURCE_MYSQL_URI