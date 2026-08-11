# app/services/macro_api_service.py
"""Клиент Macro API v2.

Все методы вызываются через POST с JSON-телом, авторизация — Bearer-токен
приложения: в спецификации у каждой операции стоит только bearerAuth, поэтому
заголовок AppId не отправляем. Лимит на ключ: 100 запросов в минуту
(sliding window), при превышении приходит 429 с заголовками X-RateLimit-*.
Поэтому вызовы сюда идут только через кэширующие сервисы, а не напрямую
из обработчиков страниц.

Документация: https://api.macroserver.ru/docs/api/v2/
"""
import logging
import threading

import requests
from flask import current_app
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

# connect, read. Карточка квартиры не должна ждать чужой сервер долго:
# планировка не критична, лучше показать страницу без неё.
REQUEST_TIMEOUT = (3, 8)

_session = None
_session_lock = threading.Lock()


class MacroApiError(Exception):
    """Любая неудача обращения к Macro: сеть, HTTP-код, неожиданный формат."""


def _get_session():
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                session = requests.Session()
                session.headers.update({
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'User-Agent': 'ApartmentFinder/1.0',
                })
                # max_retries=0: повтор на 429 только усугубит лимит.
                session.mount('https://', HTTPAdapter(pool_connections=4,
                                                      pool_maxsize=8,
                                                      max_retries=0))
                _session = session
    return _session


def is_configured():
    """Настроен ли доступ к Macro. Без него функции возвращают пустой результат,
    а страницы продолжают работать."""
    config = current_app.config
    return bool(config.get('MACRO_API_URL') and config.get('MACRO_API_TOKEN'))


def call(action, payload):
    """Вызывает метод Macro API v2 и возвращает содержимое поля `data`.

    action — путь вида 'estateSell/getFlatPlans'.
    """
    if not is_configured():
        raise MacroApiError('Доступ к Macro API не настроен (MACRO_API_URL/MACRO_API_TOKEN)')

    base_url = current_app.config['MACRO_API_URL'].rstrip('/')
    url = f'{base_url}/{action.lstrip("/")}'

    headers = {'Authorization': f'Bearer {current_app.config["MACRO_API_TOKEN"]}'}

    try:
        response = _get_session().post(url, json=payload, headers=headers,
                                       timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        raise MacroApiError(f'{action}: сеть недоступна ({exc})') from exc

    if response.status_code == 429:
        # Отдаём наверх как обычную неудачу: вызывающий закэширует негативный
        # результат и не будет долбить лимит до истечения окна.
        retry_after = response.headers.get('Retry-After', '?')
        raise MacroApiError(f'{action}: превышен лимит запросов, Retry-After={retry_after}')

    if response.status_code != 200:
        raise MacroApiError(f'{action}: HTTP {response.status_code} {response.text[:200]}')

    try:
        body = response.json()
    except ValueError as exc:
        raise MacroApiError(f'{action}: ответ не JSON') from exc

    if not isinstance(body, dict) or 'data' not in body:
        raise MacroApiError(f'{action}: в ответе нет поля data')

    return body['data']


def get_flat_plans(estate_id):
    """Файлы планировки квартиры: {'planName': str|None, 'files': [...]}.

    Поля файла: title, url, thumbUrl. URL приходят относительными
    (например '/upload/estate/plan_1.jpg') — базовый хост в MACRO_FILES_BASE_URL.
    """
    return call('estateSell/getFlatPlans', {'estateId': int(estate_id)})


def get_floor_plan(estate_id):
    """Поэтажный план объекта: {'floorPlan': {'entrance', 'floor', 'image', 'scheme'}}."""
    return call('estateSell/getFloorPlan', {'estateId': int(estate_id)})
