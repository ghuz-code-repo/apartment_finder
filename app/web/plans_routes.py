# app/web/plans_routes.py
"""Прокси и дисковый кэш картинок планировок Macro.

Браузер менеджера ходит только на наш домен — наружу выходит приложение,
как и с картографическими тайлами. Файл кэшируется по хэшу исходного URL,
поэтому сотни квартир одного типа планировки делят одну копию на диске.
"""
import hashlib
import logging
import os
import threading
from urllib.parse import urlparse

import click
import requests
from flask import Blueprint, Response, abort, current_app, send_file
from requests.adapters import HTTPAdapter

from ..core.decorators import login_required, permission_required
from ..services import flat_plan_service

logger = logging.getLogger(__name__)

plans_bp = Blueprint('plans', __name__)

CACHE_TTL = 30 * 24 * 3600
MAX_IMAGE_BYTES = 8 * 1024 * 1024
REQUEST_TIMEOUT = (3, 10)

ALLOWED_CONTENT_TYPES = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/webp': '.webp',
    'image/svg+xml': '.svg',
    'image/gif': '.gif',
}

_session = None
_session_lock = threading.Lock()


def _get_session():
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                session = requests.Session()
                session.headers.update({'User-Agent': 'ApartmentFinder/1.0',
                                        'Accept': 'image/*'})
                session.mount('https://', HTTPAdapter(pool_connections=4,
                                                      pool_maxsize=8,
                                                      max_retries=0))
                _session = session
    return _session


def _cache_dir():
    path = os.path.join(current_app.instance_path, 'plan_cache')
    os.makedirs(path, exist_ok=True)
    return path


def _cache_path(url):
    # Имя файла — хэш URL: не зависит от того, что прислал Macro, и
    # автоматически дедуплицирует одинаковые планировки разных квартир.
    digest = hashlib.sha256(url.encode('utf-8')).hexdigest()
    return os.path.join(_cache_dir(), f'{digest}.bin')


def _meta_path(cache_path):
    return f'{cache_path}.type'


def _is_host_allowed(url):
    """Скачиваем только с хоста файлового хранилища Macro.

    URL приходит из ответа стороннего API, поэтому ограничение обязательно:
    иначе подменённый ответ заставил бы наш контейнер сходить во внутреннюю сеть.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        return False
    base = current_app.config.get('MACRO_FILES_BASE_URL') or ''
    allowed = {urlparse(base).hostname} if base else set()
    extra = current_app.config.get('MACRO_FILES_ALLOWED_HOSTS') or ''
    allowed.update(host.strip().lower() for host in extra.split(',') if host.strip())
    allowed.discard(None)
    return parsed.hostname.lower() in allowed


def _store(cache_path, content, content_type):
    tmp = f'{cache_path}.{os.getpid()}.{threading.get_ident()}.tmp'
    with open(tmp, 'wb') as fh:
        fh.write(content)
    os.replace(tmp, cache_path)  # атомарно: пишут несколько воркеров
    with open(_meta_path(cache_path), 'w', encoding='utf-8') as fh:
        fh.write(content_type)


def _read_content_type(cache_path):
    try:
        with open(_meta_path(cache_path), encoding='utf-8') as fh:
            content_type = fh.read().strip()
        return content_type if content_type in ALLOWED_CONTENT_TYPES else None
    except OSError:
        return None


@plans_bp.route('/plans/<int:sell_id>/<int:index>')
@login_required
@permission_required('selection_details_view')
def plan_image(sell_id, index):
    """Отдаёт файл планировки по его номеру в кэшированном ответе Macro."""
    url = flat_plan_service.get_file_url(sell_id, index)
    if not url:
        abort(404)
    if not _is_host_allowed(url):
        logger.warning('[PLANS] Отклонён внешний адрес планировки: %s', url)
        abort(404)

    cache_path = _cache_path(url)
    content_type = _read_content_type(cache_path)
    if content_type and os.path.exists(cache_path):
        return send_file(cache_path, mimetype=content_type, max_age=CACHE_TTL,
                         conditional=True)

    try:
        response = _get_session().get(url, timeout=REQUEST_TIMEOUT, stream=True)
        response.raise_for_status()

        content_type = (response.headers.get('Content-Type') or '').split(';')[0].strip().lower()
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise ValueError(f'неожиданный тип {content_type!r}')

        content = response.raw.read(MAX_IMAGE_BYTES + 1, decode_content=True)
        if len(content) > MAX_IMAGE_BYTES:
            raise ValueError(f'файл больше {MAX_IMAGE_BYTES} байт')
    except Exception as exc:
        logger.warning('[PLANS] Планировка %s#%s не получена: %s', sell_id, index, exc)
        if os.path.exists(cache_path):
            stale_type = _read_content_type(cache_path)
            if stale_type:
                return send_file(cache_path, mimetype=stale_type, conditional=True)
        abort(404)

    _store(cache_path, content, content_type)
    return Response(content, mimetype=content_type,
                    headers={'Cache-Control': f'private, max-age={CACHE_TTL}'})


@plans_bp.cli.command('check')
@click.argument('sell_id', type=int)
@click.option('--refresh', is_flag=True, help='Игнорировать кэш и сходить в Macro.')
def check_command(sell_id, refresh):
    """Проверить получение планировки по ID объекта: flask plans check 9000001"""
    from ..services import macro_api_service

    if not macro_api_service.is_configured():
        click.echo('Macro API не настроен: заполните MACRO_API_URL и MACRO_API_TOKEN')
        return

    click.echo(f'Запрос планировки для estateId={sell_id}...')
    result = flat_plan_service.get_flat_plans(sell_id, force_refresh=refresh)

    if result['error']:
        click.echo(f'Ошибка: {result["error"]}')
        return

    click.echo(f'Название планировки: {result["plan_name"] or "(не указано)"}')
    if not result['files']:
        click.echo('Файлов нет — у этой квартиры планировка в Macro не заполнена.')
        return

    for index, item in enumerate(result['files']):
        absolute = flat_plan_service.absolutize(item['url'])
        allowed = 'ok' if absolute and _is_host_allowed(absolute) else 'ХОСТ НЕ РАЗРЕШЁН'
        click.echo(f'  [{index}] {item["title"]}')
        click.echo(f'       {item["url"]}')
        click.echo(f'       -> {absolute}  ({allowed})')
