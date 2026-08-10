# app/web/tiles_routes.py
"""Прокси и дисковый кэш картографических тайлов.

Браузер клиента ходит только на наш домен: внешние тайловые серверы
дёргает приложение. Так карта работает в изолированной сети, где клиенту
закрыт выход наружу, а контейнеру достаточно доступа к одному хосту.
"""
import logging
import os
import time

import requests
from flask import Blueprint, Response, abort, current_app, send_file

from ..core.decorators import login_required

logger = logging.getLogger(__name__)

tiles_bp = Blueprint('tiles', __name__)

# Только эти шаблоны URL могут быть использованы. Стиль из запроса служит
# ключом словаря и никогда не попадает в URL напрямую.
TILE_SOURCES = {
    'light': {
        'url': 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
        'subdomains': ('a', 'b', 'c'),
    },
    'dark': {
        'url': 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
        'subdomains': ('a', 'b', 'c', 'd'),
    },
}

MAX_ZOOM = 19
CACHE_TTL = 30 * 24 * 3600      # тайлы меняются редко
MAX_TILE_BYTES = 1024 * 1024    # реальный тайл ~10-50 КБ
REQUEST_TIMEOUT = (5, 15)       # connect, read

# Требование OSM Tile Usage Policy: приложение обязано себя назвать.
USER_AGENT = 'ApartmentFinder/1.0 (self-hosted analytics; +https://analytics.gh.uz)'

# Прозрачный PNG 1x1 — отдаём вместо тайла, когда источник недоступен,
# чтобы карта не рассыпалась на «битые картинки».
BLANK_PNG = bytes.fromhex(
    '89504e470d0a1a0a0000000d494844520000000100000001080600000'
    '01f15c4890000000a49444154789c6300010000050001'
    '0d0a2db40000000049454e44ae426082'
)


def _cache_root():
    path = os.path.join(current_app.instance_path, 'tile_cache')
    os.makedirs(path, exist_ok=True)
    return path


def _cache_path(style, z, x, y):
    # Все компоненты — проверенные целые, подстановки из запроса нет.
    return os.path.join(_cache_root(), style, str(z), str(x), f'{y}.png')


def _pick_subdomain(source, x, y):
    subs = source['subdomains']
    return subs[(x + y) % len(subs)]


def _fetch_tile(style, z, x, y):
    source = TILE_SOURCES[style]
    url = source['url'].format(s=_pick_subdomain(source, x, y), z=z, x=x, y=y)
    resp = requests.get(
        url,
        headers={'User-Agent': USER_AGENT, 'Accept': 'image/png,image/*'},
        timeout=REQUEST_TIMEOUT,
        stream=True,
    )
    resp.raise_for_status()

    content = resp.raw.read(MAX_TILE_BYTES + 1, decode_content=True)
    if len(content) > MAX_TILE_BYTES:
        raise ValueError(f'тайл больше {MAX_TILE_BYTES} байт: {url}')
    if not content.startswith(b'\x89PNG'):
        raise ValueError(f'ответ не PNG: {url}')
    return content


@tiles_bp.route('/tiles/<style>/<int:z>/<int:x>/<int:y>.png')
@login_required
def tile(style, z, x, y):
    if style not in TILE_SOURCES:
        abort(404)
    if not 0 <= z <= MAX_ZOOM:
        abort(404)
    limit = 1 << z
    if not (0 <= x < limit and 0 <= y < limit):
        abort(404)

    path = _cache_path(style, z, x, y)
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_TTL:
        return send_file(path, mimetype='image/png', max_age=CACHE_TTL)

    try:
        content = _fetch_tile(style, z, x, y)
    except Exception as exc:
        logger.warning('Тайл %s/%s/%s/%s не получен: %s', style, z, x, y, exc)
        if os.path.exists(path):
            # Протухший кэш лучше пустого места.
            return send_file(path, mimetype='image/png', max_age=CACHE_TTL)
        return Response(BLANK_PNG, mimetype='image/png',
                        headers={'Cache-Control': 'no-store'})

    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.{os.getpid()}.tmp'
    with open(tmp, 'wb') as fh:
        fh.write(content)
    os.replace(tmp, path)  # атомарно: под gunicorn пишут несколько воркеров

    return Response(content, mimetype='image/png',
                    headers={'Cache-Control': f'public, max-age={CACHE_TTL}'})