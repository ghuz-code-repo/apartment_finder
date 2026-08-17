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

from ..core.decorators import (_get_current_user, _is_gateway_user, any_permission_granted,
                               login_required, user_permissions)
from ..services import flat_plan_service, macro_api_service

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


def _allowed_hosts():
    """Хосты, с которых разрешено качать файлы планировок.

    Хост самого API входит сюда всегда: чаще всего Macro отдаёт файлы оттуда же,
    а MACRO_FILES_BASE_URL нужен только чтобы достроить относительный путь —
    без этого умолчания абсолютные URL из ответа отвергались бы все до одного.
    """
    config = current_app.config
    allowed = set()
    for source in (config.get('MACRO_FILES_BASE_URL'), config.get('MACRO_API_URL')):
        host = urlparse(source or '').hostname
        if host:
            allowed.add(host.lower())
    extra = config.get('MACRO_FILES_ALLOWED_HOSTS') or ''
    allowed.update(host.strip().lower() for host in extra.split(',') if host.strip())
    return allowed


def _is_host_allowed(url):
    """Скачиваем только с хоста файлового хранилища Macro.

    URL приходит из ответа стороннего API, поэтому ограничение обязательно:
    иначе подменённый ответ заставил бы наш контейнер сходить во внутреннюю сеть.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        return False
    return parsed.hostname.lower() in _allowed_hosts()


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


# Планировку показывают две страницы, и права на них разные: карточку смотрит
# один менеджер, КП может открывать другой. Хватает любого из двух прав, иначе
# в КП вместо планировки была бы дыра.
PLAN_PERMISSIONS = ('selection_details_view', 'selection_commercial_offer_view')


def _can_view_plans():
    user = _get_current_user()
    if not user or not _is_gateway_user(user):
        return False

    return any_permission_granted(PLAN_PERMISSIONS, user_permissions(user))


@plans_bp.route('/plans/<int:sell_id>/<int:index>')
@login_required
def plan_image(sell_id, index):
    """Отдаёт файл планировки по его номеру в кэшированном ответе Macro."""
    if not _can_view_plans():
        abort(403)

    # Разбираем по шагам, а не через get_file_url: у 404 тут пять разных причин,
    # и без записи в лог их не отличить.
    plans = flat_plan_service.get_flat_plans(sell_id)
    files = plans.get('files') or []
    if not files:
        logger.warning('[PLANS] У объекта %s нет файлов планировки (ошибка: %s)',
                       sell_id, plans.get('error') or 'нет, Macro вернул пустой список')
        abort(404)
    if index >= len(files):
        logger.warning('[PLANS] У объекта %s запрошен файл %s, а их всего %s (нумерация с нуля)',
                       sell_id, index, len(files))
        abort(404)

    url = flat_plan_service.absolutize(files[index]['url'])
    if not url:
        logger.warning('[PLANS] Путь %r не достроен до адреса — задайте MACRO_FILES_BASE_URL',
                       files[index]['url'])
        abort(404)
    if not _is_host_allowed(url):
        logger.warning('[PLANS] Отклонён внешний адрес планировки: %s (разрешены: %s)',
                       url, ', '.join(sorted(_allowed_hosts())) or 'ни одного')
        abort(404)

    cache_path = _cache_path(url)
    content_type = _read_content_type(cache_path)
    if content_type and os.path.exists(cache_path):
        return send_file(cache_path, mimetype=content_type, max_age=CACHE_TTL,
                         conditional=True)

    try:
        response = _get_session().get(url, timeout=REQUEST_TIMEOUT, stream=True,
                                      verify=macro_api_service.ssl_verify())
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
def check_command(sell_id):
    """Диагностика планировки по ID объекта: flask plans check 5622160

    Показывает настройки, сырой ответ Macro и доступность каждого файла.
    Кэш не используется — запрос уходит на сервер Macro каждый раз.
    """
    import json
    import socket
    from urllib.parse import urlparse

    from ..services.macro_api_service import MacroApiError

    config = current_app.config
    click.echo('--- Настройки ---')
    click.echo(f'  MACRO_API_URL         = {config.get("MACRO_API_URL") or "(пусто)"}')
    # Сам токен не печатаем: вывод команды часто уходит в переписку.
    token = config.get('MACRO_API_TOKEN') or ''
    click.echo(f'  MACRO_API_TOKEN       = {"задан, " + str(len(token)) + " символов" if token else "(пусто)"}')
    click.echo(f'  MACRO_FILES_BASE_URL  = {config.get("MACRO_FILES_BASE_URL") or "(пусто)"}')
    click.echo(f'  MACRO_API_VERIFY_SSL  = {config.get("MACRO_API_VERIFY_SSL")}')
    click.echo(f'  разрешённые хосты     = {", ".join(sorted(_allowed_hosts())) or "(ни одного)"}')

    # Куда контейнер реально резолвит имя: расхождение с адресом MySQL-источника
    # означает, что DNS хоста отдаёт внешний адрес и до него нет маршрута.
    api_host = urlparse(config.get('MACRO_API_URL') or '').hostname
    if api_host:
        try:
            click.echo(f'  {api_host} -> {socket.gethostbyname(api_host)}')
        except OSError as exc:
            click.echo(f'  {api_host} -> ИМЯ НЕ РЕЗОЛВИТСЯ: {exc}')

    if not macro_api_service.is_configured():
        click.echo('\nMacro API не настроен: заполните MACRO_API_URL и MACRO_API_TOKEN в .env')
        return

    click.echo(f'\n--- Запрос estateSell/getFlatPlans {{"estateId": {sell_id}}} ---')
    try:
        data = macro_api_service.get_flat_plans(sell_id)
    except MacroApiError as exc:
        click.echo(f'  ОШИБКА: {exc}')
        click.echo('\n  Если это HTTP 404 или "нет поля data" — проверьте, что MACRO_API_URL')
        click.echo('  заканчивается версией (.../v2) и что ID существует в Macro.')
        return

    click.echo('  Ответ (поле data):')
    click.echo(json.dumps(data, ensure_ascii=False, indent=2))

    files = flat_plan_service._normalize_files(data.get('files'))
    click.echo(f'\n--- Разбор: файлов {len(files)} ---')
    if not files:
        click.echo('  Планировка у этой квартиры в Macro не заполнена либо поле files пустое.')
        return

    session = _get_session()
    for index, item in enumerate(files):
        absolute = flat_plan_service.absolutize(item['url'])
        click.echo(f'  [{index}] {item["title"]}')
        click.echo(f'       путь из Macro: {item["url"]}')
        click.echo(f'       полный адрес:  {absolute or "НЕ СОБРАН — задайте MACRO_FILES_BASE_URL"}')
        if not absolute:
            continue
        if not _is_host_allowed(absolute):
            click.echo('       ХОСТ НЕ РАЗРЕШЁН — добавьте его в MACRO_FILES_BASE_URL '
                       'или MACRO_FILES_ALLOWED_HOSTS')
            continue
        try:
            response = session.get(absolute, timeout=REQUEST_TIMEOUT, stream=True,
                                   verify=macro_api_service.ssl_verify())
            content_type = (response.headers.get('Content-Type') or '').split(';')[0].strip()
            verdict = 'ok' if content_type in ALLOWED_CONTENT_TYPES else 'ТИП НЕ ПОДДЕРЖИВАЕТСЯ'
            click.echo(f'       загрузка: HTTP {response.status_code}, {content_type or "без типа"} ({verdict})')
            response.close()
        except Exception as exc:
            click.echo(f'       загрузка: НЕ УДАЛАСЬ — {exc}')


@plans_bp.cli.command('purge')
@click.argument('sell_id', type=int)
def purge_command(sell_id):
    """Сбрасывает кэш планировки: flask plans purge 5139408

    Неудачный запрос к Macro кэшируется на час, поэтому после починки доступа
    страница ещё час отдаёт пустоту — эта команда снимает блок сразу.
    """
    if flat_plan_service.forget(sell_id):
        click.echo(f'Кэш планировки {sell_id} сброшен — следующий запрос уйдёт в Macro.')
    else:
        click.echo(f'Записи по {sell_id} в кэше не было.')
