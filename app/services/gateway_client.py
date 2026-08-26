# app/services/gateway_client.py
"""Обращения к auth-service шлюза.

Пользователи сервиса живут в шлюзе, а не у нас: список нужен, чтобы связывать
менеджеров CRM выбором из готовых учётных записей, а не вводом логина руками.

Адрес доставки уведомлений здесь не резолвится: notification-service принимает
логин портала и находит chat_id сам — хранить у себя ник или chat_id значило бы
завести второй источник правды.

Вызовы подписаны X-API-Key и не роняют страницу: при недоступности шлюза
возвращаем None, а вызывающий показывает это пользователю.
"""

import logging
import os

import requests
from flask import current_app

logger = logging.getLogger(__name__)

SERVICE_KEY = 'finder'
DEFAULT_TIMEOUT = 10


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
    Различать важно: «нет доступа к шлюзу» и «людей там нет» лечатся по-разному,
    а сообщение на странице должно называть настоящую причину.
    """
    data = _get(f'/api/services/{SERVICE_KEY}/users')
    # Эндпоинт отдаёт массив; объект приходит только при ошибке.
    return data if isinstance(data, list) else None


def find_user(username, users=None):
    """Запись пользователя шлюза по логину."""
    if not username:
        return None
    target = str(username).strip().lower()
    for user in (users if users is not None else (list_service_users() or [])):
        if str(user.get('username', '')).strip().lower() == target:
            return user
    return None
