# app/services/gateway_client.py
"""Обращения к auth-service шлюза.

Пользователи сервиса и привязка Telegram живут в шлюзе, а не у нас. Раньше
логин и telegram-ник вбивались руками — здесь они берутся из источника, где
уже настроены, поэтому расходиться им негде.

Все вызовы подписаны X-API-Key и не роняют страницу: при недоступности шлюза
возвращаем пустой результат, а вызывающий показывает это пользователю.
"""

import logging
import os

import requests
from flask import current_app

logger = logging.getLogger(__name__)

SERVICE_KEY = 'finder'
DEFAULT_TIMEOUT = 10
# Поля, под которыми в разных ответах шлюза встречается telegram-ник.
TELEGRAM_USERNAME_FIELDS = ('telegram_username', 'telegram_login', 'telegram')
TELEGRAM_CHAT_ID_FIELDS = ('telegram_chat_id', 'chat_id')


def _base_url():
    return (current_app.config.get('AUTH_SERVICE_URL')
            or os.environ.get('AUTH_SERVICE_URL')
            or 'http://auth-service:80').rstrip('/')


def _api_key():
    return (current_app.config.get('INTERNAL_API_KEY')
            or os.environ.get('INTERNAL_API_KEY', ''))


def _get(path, params=None):
    """GET к auth-service. None — не получилось, причина уже в логе."""
    api_key = _api_key()
    if not api_key:
        logger.warning("INTERNAL_API_KEY не задан — запрос к шлюзу пропущен: %s", path)
        return None

    try:
        response = requests.get(
            f'{_base_url()}{path}',
            params=params,
            headers={'X-API-Key': api_key},
            timeout=DEFAULT_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error("Шлюз недоступен (%s): %s", path, e)
        return None
    except ValueError as e:
        logger.error("Шлюз ответил не-JSON (%s): %s", path, e)
        return None


def list_service_users():
    """Пользователи нашего сервиса из шлюза.

    None — шлюз не ответил, пустой список — ответил, но пользователей нет.
    Различать важно: «нет доступа к шлюзу» и «человека там нет» лечатся
    по-разному, а сообщение пользователю должно называть настоящую причину.
    """
    data = _get(f'/api/services/{SERVICE_KEY}/users')
    # Эндпоинт отдаёт массив; объект приходит только при ошибке.
    return data if isinstance(data, list) else None


def get_user_profile(user_id):
    """Профиль пользователя шлюза или None."""
    if not user_id:
        return None
    data = _get(f'/api/users/{user_id}/profile')
    return data if isinstance(data, dict) else None


def _first_field(source, fields):
    """Первое непустое значение из перечисленных полей."""
    if not isinstance(source, dict):
        return None
    for field in fields:
        value = source.get(field)
        if value:
            return str(value).strip()
    return None


def find_user(username, users=None):
    """Запись пользователя шлюза по логину."""
    if not username:
        return None
    target = str(username).strip().lower()
    for user in (users if users is not None else (list_service_users() or [])):
        if str(user.get('username', '')).strip().lower() == target:
            return user
    return None


def resolve_chat_id(telegram_username):
    """telegram-ник -> chat_id. None, если привязки нет.

    Шлюз на отсутствие привязки отвечает 200 с success=false, поэтому смотрим
    на поле, а не на код ответа.
    """
    if not telegram_username:
        return None

    data = _get('/api/telegram/chat-id', params={'username': str(telegram_username).lstrip('@')})
    if not isinstance(data, dict) or not data.get('success'):
        return None

    chat_id = data.get('chat_id')
    return str(chat_id) if chat_id else None


def get_telegram_target(username, users=None):
    """Куда слать сообщения этому пользователю.

    Возвращает словарь с chat_id, ником и причиной, если отправить нельзя:
    ник нигде не вводится руками, поэтому «не привязан» — это указание сходить
    в личный кабинет портала, а не в наши настройки.
    """
    if users is None:
        users = list_service_users()
        if users is None:
            return {'chat_id': None, 'telegram_username': None,
                    'problem': 'Не удалось получить данные из шлюза: проверьте доступность '
                               'auth-service и INTERNAL_API_KEY.'}

    user = find_user(username, users)
    if not user:
        return {'chat_id': None, 'telegram_username': None,
                'problem': 'Пользователь не найден среди пользователей сервиса в шлюзе — '
                           'обратитесь к администратору портала.'}

    # Готовый chat_id в записи пользователя избавляет от лишнего запроса.
    chat_id = _first_field(user, TELEGRAM_CHAT_ID_FIELDS)
    nick = _first_field(user, TELEGRAM_USERNAME_FIELDS)

    if not chat_id and not nick:
        # В списке телеграм-полей может не быть — профиль полнее.
        profile = get_user_profile(user.get('id'))
        chat_id = chat_id or _first_field(profile, TELEGRAM_CHAT_ID_FIELDS)
        nick = nick or _first_field(profile, TELEGRAM_USERNAME_FIELDS)

    if not chat_id and nick:
        chat_id = resolve_chat_id(nick)

    if chat_id:
        return {'chat_id': chat_id, 'telegram_username': nick, 'problem': None}

    if nick:
        return {'chat_id': None, 'telegram_username': nick,
                'problem': f'Ник @{nick} указан в профиле, но чат с ботом не подтверждён. '
                           f'Откройте личный кабинет портала и завершите подключение Telegram.'}

    return {'chat_id': None, 'telegram_username': None,
            'problem': 'Telegram не подключён в личном кабинете портала. '
                       'Подключите его в разделе «Безопасность» и повторите проверку.'}
