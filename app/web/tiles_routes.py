# app/web/tiles_routes.py
"""Прокси и дисковый кэш картографических тайлов.

Браузер клиента ходит только на наш домен: внешние тайловые серверы
дёргает приложение. Так карта работает в изолированной сети, где клиенту
закрыт выход наружу, а контейнеру достаточно доступа к одному хосту.
"""
import logging
import math
import os
import threading
import time

import click
import requests
from flask import (Blueprint, Response, abort, current_app, jsonify, request,
                   send_file, stream_with_context, url_for)
from requests.adapters import HTTPAdapter

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
CACHE_TTL = 180 * 24 * 3600     # базовая картография меняется медленно
MAX_TILE_BYTES = 1024 * 1024    # реальный тайл ~10-50 КБ
# Короткий таймаут намеренно: тайл держит поток, и лучше быстро отдать
# заглушку, чем занимать воркер на секунды из-за одной подвисшей плитки.
REQUEST_TIMEOUT = (2, 6)        # connect, read
NEGATIVE_TTL = 300              # столько не долбим источник после неудачи

# Требование OSM Tile Usage Policy: приложение обязано себя назвать.
USER_AGENT = 'ApartmentFinder/1.0 (self-hosted analytics; +https://analytics.gh.uz)'

# Прозрачный PNG 1x1 — отдаём вместо тайла, когда источник недоступен,
# чтобы карта не рассыпалась на «битые картинки».
BLANK_PNG = bytes.fromhex(
    '89504e470d0a1a0a0000000d494844520000000100000001080600000'
    '01f15c4890000000a49444154789c6300010000050001'
    '0d0a2db40000000049454e44ae426082'
)

# Один пул соединений на процесс: без него каждый холодный тайл платил
# за новый TCP+TLS handshake, а их при зуме десятки.
_session = None
_session_lock = threading.Lock()
# Недавние неудачи: {(style, z, x, y): время}. Ограничивает шторм запросов
# к лежащему источнику.
_failures = {}


def _get_session():
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                s = requests.Session()
                s.headers.update({'User-Agent': USER_AGENT,
                                  'Accept': 'image/png,image/*'})
                adapter = HTTPAdapter(pool_connections=8, pool_maxsize=32,
                                      max_retries=0)
                s.mount('https://', adapter)
                _session = s
    return _session


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
    resp = _get_session().get(url, timeout=REQUEST_TIMEOUT, stream=True)
    resp.raise_for_status()

    content = resp.raw.read(MAX_TILE_BYTES + 1, decode_content=True)
    if len(content) > MAX_TILE_BYTES:
        raise ValueError(f'тайл больше {MAX_TILE_BYTES} байт: {url}')
    if not content.startswith(b'\x89PNG'):
        raise ValueError(f'ответ не PNG: {url}')
    return content


def _store_tile(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.{os.getpid()}.{threading.get_ident()}.tmp'
    with open(tmp, 'wb') as fh:
        fh.write(content)
    os.replace(tmp, path)  # атомарно: пишут несколько воркеров и потоков


def _serve_cached(path):
    # conditional=True добавляет ETag/Last-Modified: повторный заход отдаёт
    # 304 без тела, а send_file делегирует отдачу файла WSGI-серверу.
    return send_file(path, mimetype='image/png', max_age=CACHE_TTL,
                     conditional=True)


def _tar_header(name, size):
    """Заголовок ustar. Формат простой и позволяет отдавать архив потоком,
    не собирая гигабайт в памяти и не завися от внешних библиотек."""
    name_bytes = name.encode('utf-8')[:100]
    fields = [
        name_bytes.ljust(100, b'\0'),
        b'0000644\0',                       # mode
        b'0000000\0', b'0000000\0',         # uid, gid
        f'{size:011o}\0'.encode(),          # size
        f'{0:011o}\0'.encode(),             # mtime — ноль, чтобы архив был
                                            # побайтно одинаковым между сборками
        b' ' * 8,                           # checksum, считается ниже
        b'0',                               # обычный файл
        b'\0' * 100,                        # linkname
        b'ustar\x0000',
        b'\0' * 32, b'\0' * 32,             # uname, gname
        b'0000000\0', b'0000000\0',         # devmajor, devminor
        b'\0' * 155,
    ]
    header = b''.join(fields).ljust(512, b'\0')
    checksum = sum(header)
    header = header[:148] + f'{checksum:06o}\0 '.encode() + header[156:]
    return header


def _bundle_root():
    path = os.path.join(current_app.instance_path, 'tile_bundles')
    os.makedirs(path, exist_ok=True)
    return path


def _bundle_path(region_id):
    return os.path.join(_bundle_root(), f'{region_id}.tar')


def _iter_region_tar(cache_root, region, styles=None):
    """Куски tar для региона. Отдаёт только то, что уже лежит в кэше.

    Архив содержит все стили сразу: тему на карте переключают на ходу, и
    сохранённый регион должен работать в обеих. Стиль записан в имени файла
    внутри архива, поэтому распаковщику отдельный признак не нужен.
    """
    for style in (styles or sorted(TILE_SOURCES)):
        for layer in region['layers']:
            for z, x, y in iter_tiles(layer['bbox'], layer['min_zoom'],
                                      layer['max_zoom']):
                path = os.path.join(cache_root, style, str(z), str(x), f'{y}.png')
                try:
                    size = os.path.getsize(path)
                    with open(path, 'rb') as fh:
                        data = fh.read()
                except OSError:
                    continue    # нет в кэше — клиент возьмёт через прокси
                if len(data) != size:
                    continue
                yield _tar_header(f'{style}/{z}/{x}/{y}.png', size)
                yield data
                padding = -size % 512
                if padding:
                    yield b'\0' * padding
    yield b'\0' * 1024          # признак конца архива


@tiles_bp.route('/tiles/region/<region_id>/bundle')
@login_required
def region_bundle(region_id):
    """Отдаёт весь регион одним потоком.

    Сорок тысяч отдельных запросов упираются не в канал, а в накладные
    расходы на каждый: проверку сессии, заголовки, обход стека. Здесь клиент
    получает то же самое одним tar, а недостающее (чего нет в кэше сервера)
    дотягивает обычным путём.
    """
    region = REGIONS.get(region_id)
    if not region:
        abort(404)

    filename = f'{region_id}.tar'
    packed = _bundle_path(region_id)

    # Готовый файл отдаётся на порядок быстрее, чем собранный на лету: ядро
    # переливает его в сокет само, без чтения тысяч файлов и без прохода
    # данных через Python. Замер на 75 МБ: 252 МБ/с против 1029 МБ/с.
    if os.path.exists(packed):
        accel = current_app.config.get('TILES_XACCEL_PREFIX')
        if accel:
            # nginx отдаёт файл через sendfile(), приложение освобождается
            # сразу и не занимает поток на время выгрузки.
            response = Response(mimetype='application/x-tar')
            response.headers['X-Accel-Redirect'] = accel.rstrip('/') + '/' + filename
        else:
            # conditional=True добавляет поддержку докачки по Range.
            response = send_file(packed, mimetype='application/x-tar',
                                 conditional=True, max_age=0)
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    # Пакет не собран — отдаём потоком, чтобы кнопка работала в любом случае.
    response = Response(
        stream_with_context(_iter_region_tar(_cache_root(), region)),
        mimetype='application/x-tar')
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.headers['Cache-Control'] = 'no-store'
    return response


@tiles_bp.route('/tiles-sw.js')
def tiles_service_worker():
    """Отдаёт воркер тайлов из корня приложения.

    Service Worker управляет только теми путями, что лежат ниже адреса, с
    которого он отдан. Из /static/js/ он бы не увидел /tiles/, поэтому файл
    выдаётся отсюда и с заголовком Service-Worker-Allowed.

    Без авторизации намеренно: это статический скрипт без данных, а браузер
    запрашивает его вне сессии страницы.
    """
    path = os.path.join(current_app.static_folder, 'js', 'tiles-sw.js')
    response = send_file(path, mimetype='application/javascript',
                         max_age=0, conditional=True)
    # Разрешаем воркеру обслуживать всё приложение, а не только свою папку.
    response.headers['Service-Worker-Allowed'] = url_for('main.index')
    return response


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
        return _serve_cached(path)

    key = (style, z, x, y)
    failed_at = _failures.get(key)
    if failed_at and time.time() - failed_at < NEGATIVE_TTL:
        if os.path.exists(path):
            return _serve_cached(path)
        return Response(BLANK_PNG, mimetype='image/png',
                        headers={'Cache-Control': 'no-store'})

    try:
        content = _fetch_tile(style, z, x, y)
    except Exception as exc:
        logger.warning('Тайл %s/%s/%s/%s не получен: %s', style, z, x, y, exc)
        _failures[key] = time.time()
        if len(_failures) > 10000:
            _failures.clear()
        if os.path.exists(path):
            # Протухший кэш лучше пустого места.
            return _serve_cached(path)
        return Response(BLANK_PNG, mimetype='image/png',
                        headers={'Cache-Control': 'no-store'})

    _failures.pop(key, None)
    _store_tile(path, content)
    return Response(content, mimetype='image/png',
                    headers={'Cache-Control': f'public, max-age={CACHE_TTL}'})


# --------------------------------------------------------------------------
# Предзагрузка кэша
# --------------------------------------------------------------------------

def _deg2tile(lat, lon, z):
    n = 1 << z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def iter_tiles(bbox, min_zoom, max_zoom):
    """Перечисляет тайлы, покрывающие bbox = (south, west, north, east)."""
    south, west, north, east = bbox
    for z in range(min_zoom, max_zoom + 1):
        x1, y1 = _deg2tile(north, west, z)
        x2, y2 = _deg2tile(south, east, z)
        for x in range(min(x1, x2), max(x1, x2) + 1):
            for y in range(min(y1, y2), max(y1, y2) + 1):
                yield z, x, y


# Ташкент с запасом: от Чирчика до Зангиаты.
DEFAULT_BBOX = (41.16, 69.05, 41.45, 69.45)

# Готовые к загрузке регионы. Детализация падает по мере удаления от центра:
# область целиком на всех зумах — это 618 тысяч плиток и почти 15 ГБ, тогда
# как ступенчатая нарезка даёт те же 40 тысяч и меньше гигабайта. Так же
# устроены офлайн-карты: периферию незачем держать в максимальной детализации.
REGIONS = {
    'tashkent': {
        'title': 'Ташкент и область',
        'center': (41.31, 69.24),
        'zoom': 11,
        'layers': [
            {'bbox': (40.50, 68.20, 41.75, 70.30), 'min_zoom': 8,  'max_zoom': 13},
            {'bbox': (40.95, 68.75, 41.65, 69.90), 'min_zoom': 14, 'max_zoom': 15},
            {'bbox': (41.16, 69.05, 41.45, 69.45), 'min_zoom': 16, 'max_zoom': 17},
        ],
    },
    'moscow': {
        'title': 'Москва и область',
        'center': (55.75, 37.62),
        'zoom': 10,
        'layers': [
            {'bbox': (54.20, 35.10, 56.95, 40.20), 'min_zoom': 8,  'max_zoom': 12},
            {'bbox': (55.20, 36.60, 56.20, 38.40), 'min_zoom': 13, 'max_zoom': 15},
            {'bbox': (55.55, 37.35, 55.92, 37.85), 'min_zoom': 16, 'max_zoom': 17},
        ],
    },
}


def region_tile_count(region):
    return sum(sum(1 for _ in iter_tiles(layer['bbox'],
                                         layer['min_zoom'], layer['max_zoom']))
               for layer in region['layers'])


def _sample_tile_bytes(cache_root, style, limit=200):
    """Средний вес плитки по выборке из кэша.

    Обходить десятки тысяч файлов ради точной суммы дороже, чем сама выгрузка,
    поэтому берём выборку. Пустой кэш — возвращаем None, и вес считается по
    оценочной константе.
    """
    root = os.path.join(cache_root, style)
    if not os.path.isdir(root):
        return None
    sizes = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if not name.endswith('.png'):
                continue
            try:
                sizes.append(os.path.getsize(os.path.join(dirpath, name)))
            except OSError:
                continue
            if len(sizes) >= limit:
                return sum(sizes) / len(sizes)
    return sum(sizes) / len(sizes) if sizes else None


@tiles_bp.route('/tiles/regions')
@login_required
def regions():
    """Описание регионов и ожидаемый вес — чтобы кнопка загрузки называла
    честную цифру, а не константу из головы.

    Считаем сразу по всем стилям: тему переключают на ходу, и сохранённый
    регион обязан работать в обеих, иначе в тёмной карта окажется пустой.
    """
    styles = sorted(TILE_SOURCES)
    cache_root = _cache_root()

    samples = [s for s in (_sample_tile_bytes(cache_root, style)
                           for style in styles) if s is not None]
    measured = bool(samples)
    avg = sum(samples) / len(samples) if samples else 25 * 1024

    payload = []
    for region_id, region in REGIONS.items():
        per_style = region_tile_count(region)
        tiles = per_style * len(styles)
        payload.append({
            'id': region_id,
            'title': region['title'],
            'center': list(region['center']),
            'zoom': region['zoom'],
            'styles': styles,
            'tilesPerStyle': per_style,
            'tiles': tiles,
            'bytes': int(tiles * avg),
            'avgTileBytes': int(avg),
            'measured': measured,
            'layers': [
                {'bbox': list(layer['bbox']),
                 'minZoom': layer['min_zoom'],
                 'maxZoom': layer['max_zoom']}
                for layer in region['layers']
            ],
        })
    return jsonify({'regions': payload, 'styles': styles})


def seed_tiles(cache_root, bbox, style='light', min_zoom=10, max_zoom=17,
               workers=4, delay=0.05, progress=None):
    """Скачивает недостающие тайлы района. Уже сохранённые пропускает.

    cache_root передаётся готовым: функция работает и из потока, где
    контекста приложения нет.
    """
    from concurrent.futures import ThreadPoolExecutor

    targets = list(iter_tiles(bbox, min_zoom, max_zoom))
    stats = {'ok': 0, 'cached': 0, 'fail': 0, 'total': len(targets)}
    lock = threading.Lock()

    def work(item):
        z, x, y = item
        path = os.path.join(cache_root, style, str(z), str(x), f'{y}.png')
        if os.path.exists(path):
            with lock:
                stats['cached'] += 1
            return
        try:
            content = _fetch_tile(style, z, x, y)
            _store_tile(path, content)
            with lock:
                stats['ok'] += 1
        except Exception as exc:
            with lock:
                stats['fail'] += 1
            logger.debug('seed %s/%s/%s/%s: %s', style, z, x, y, exc)
        # Пауза сознательно: OSM Tile Usage Policy не разрешает выкачивать
        # тайлы на полной скорости, и агрессивный seed приводит к бану.
        time.sleep(delay)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, _ in enumerate(pool.map(work, targets), 1):
            if progress and i % 500 == 0:
                progress(i, stats)
    return stats


# --------------------------------------------------------------------------
# Автоматический прогрев при старте
# --------------------------------------------------------------------------

def _seed_signature(bbox, style, min_zoom, max_zoom):
    coords = ','.join(f'{c:.4f}' for c in bbox)
    return f'{style}|{coords}|{min_zoom}-{max_zoom}'


# Владелец лока обновляет его метку времени, пока работает. Лок лежит в
# смонтированной директории и переживает контейнер, поэтому «свежесть»
# определяется этими обновлениями, а не фактом существования файла.
LOCK_HEARTBEAT = 30
LOCK_STALE_AFTER = 120


def _try_acquire_lock(lock_path, stale_after=LOCK_STALE_AFTER):
    """Отдаёт лок ровно одному процессу. gunicorn импортирует модуль в
    каждом воркере, и без этого они полезли бы качать одно и то же."""
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        try:
            age = time.time() - os.path.getmtime(lock_path)
            # Прошлый контейнер могли убить на середине: daemon-поток умирает
            # мгновенно, лок остаётся, и без этой проверки прогрев больше
            # никогда бы не запустился.
            if age > stale_after:
                logger.info('[TILES] Снимаю зависший лок (возраст %.0f c)', age)
                os.unlink(lock_path)
                return _try_acquire_lock(lock_path, stale_after)
        except OSError:
            pass
        return False


def _touch_lock(lock_path, stop_event):
    """Держит лок живым, пока идёт прогрев."""
    while not stop_event.wait(LOCK_HEARTBEAT):
        try:
            os.utime(lock_path, None)
        except OSError:
            return


def start_background_seed(app):
    """Прогревает кэш тайлов в фоне после старта приложения.

    Включается TILE_SEED_ON_STARTUP=1. Работа идёт в daemon-потоке: seed
    занимает десятки минут, и держать на нём старт gunicorn нельзя —
    healthcheck не дождётся.
    """
    raw_flag = os.getenv('TILE_SEED_ON_STARTUP', '0')
    if raw_flag.strip().lower() not in ('1', 'true', 'yes'):
        app.logger.info('[TILES] Прогрев выключен (TILE_SEED_ON_STARTUP=%r)', raw_flag)
        return

    style = os.getenv('TILE_SEED_STYLE', 'light')
    min_zoom = int(os.getenv('TILE_SEED_MIN_ZOOM', '10'))
    max_zoom = int(os.getenv('TILE_SEED_MAX_ZOOM', '17'))
    workers = int(os.getenv('TILE_SEED_WORKERS', '2'))
    delay = float(os.getenv('TILE_SEED_DELAY', '0.1'))
    raw_bbox = os.getenv('TILE_SEED_BBOX', '')
    if raw_bbox:
        try:
            bbox = tuple(float(v) for v in raw_bbox.replace(',', ' ').split())
            if len(bbox) != 4:
                raise ValueError('нужно четыре числа: SOUTH WEST NORTH EAST')
        except ValueError as exc:
            app.logger.error('[TILES] TILE_SEED_BBOX игнорируется: %s', exc)
            bbox = DEFAULT_BBOX
    else:
        bbox = DEFAULT_BBOX

    if style not in TILE_SOURCES or not 0 <= min_zoom <= max_zoom <= MAX_ZOOM:
        app.logger.error('[TILES] Некорректные параметры прогрева, пропуск')
        return

    with app.app_context():
        cache_root = _cache_root()
    signature = _seed_signature(bbox, style, min_zoom, max_zoom)
    done_marker = os.path.join(cache_root, '.seed-done')
    lock_path = os.path.join(cache_root, '.seed-lock')

    # Тот же участок уже прогрет — при каждом рестарте заново не ходим.
    if os.path.exists(done_marker):
        try:
            with open(done_marker) as fh:
                if fh.read().strip() == signature:
                    app.logger.info('[TILES] Район уже прогрет: %s', signature)
                    return
        except OSError:
            pass

    if not _try_acquire_lock(lock_path):
        app.logger.info('[TILES] Прогрев уже идёт в другом воркере, пропуск')
        return

    def run():
        time.sleep(float(os.getenv('TILE_SEED_START_DELAY', '20')))
        started = time.time()
        app.logger.info('[TILES] Прогрев кэша: %s', signature)
        # Пока идёт закачка, обновляем метку лока: если контейнер убьют,
        # обновления прекратятся и следующий старт заберёт лок себе.
        stop_heartbeat = threading.Event()
        threading.Thread(target=_touch_lock, args=(lock_path, stop_heartbeat),
                         daemon=True, name='tile-seed-lock').start()
        try:
            def progress(i, stats):
                app.logger.info('[TILES] %s/%s скачано=%s из кэша=%s ошибок=%s',
                                i, stats['total'], stats['ok'],
                                stats['cached'], stats['fail'])
            stats = seed_tiles(cache_root, bbox, style, min_zoom, max_zoom,
                               workers, delay, progress)
            app.logger.info(
                '[TILES] Прогрев завершён за %.0f c: скачано=%s из кэша=%s ошибок=%s',
                time.time() - started, stats['ok'], stats['cached'], stats['fail'])
            # Маркер ставим, только если район покрыт полностью, иначе при
            # следующем старте попробуем снова.
            if stats['fail'] == 0:
                with open(done_marker, 'w') as fh:
                    fh.write(signature)
        except Exception as exc:
            app.logger.error('[TILES] Прогрев прерван: %s', exc)
        finally:
            stop_heartbeat.set()
            try:
                os.unlink(lock_path)
            except OSError:
                pass

    threading.Thread(target=run, daemon=True, name='tile-seed').start()


@tiles_bp.cli.command('pack-region')
@click.option('--region', type=click.Choice(sorted(REGIONS)), default=None,
              help='По умолчанию собираются все регионы.')
def pack_region_command(region):
    """Собрать регионы в файлы, чтобы отдавать их без участия Python.

    В пакет попадают все стили сразу: карта переключает тему на ходу, и
    сохранённый регион должен работать в обеих. Запускать после seed-region
    и при обновлении плиток — пакет статичен и сам себя не обновляет.
    """
    cache_root = _cache_root()
    region_ids = [region] if region else sorted(REGIONS)
    total_written = 0

    for region_id in region_ids:
        definition = REGIONS[region_id]
        target = _bundle_path(region_id)
        tmp = target + '.tmp'

        written = 0
        with open(tmp, 'wb') as fh:
            for chunk in _iter_region_tar(cache_root, definition):
                fh.write(chunk)
                written += len(chunk)
        os.replace(tmp, target)
        total_written += written
        click.echo(f'{definition["title"]}: {written / 1048576:.0f} МБ -> {target}')

    click.echo(f'Готово: {len(region_ids)} пакет(ов), '
               f'{total_written / 1073741824:.2f} ГБ, '
               f'стили: {", ".join(sorted(TILE_SOURCES))}')
    click.echo('  Отдаются как статические файлы; если задан TILES_XACCEL_PREFIX, '
               'выгрузку берёт на себя nginx.')


@tiles_bp.cli.command('seed-region')
@click.option('--region', type=click.Choice(sorted(REGIONS)), default=None,
              help='По умолчанию прогреваются все регионы.')
@click.option('--style', type=click.Choice(sorted(TILE_SOURCES)), default=None,
              help='По умолчанию прогреваются все стили.')
@click.option('--workers', type=int, default=4, show_default=True)
@click.option('--delay', type=float, default=0.05, show_default=True)
def seed_region_command(region, style, workers, delay):
    """Прогреть кэш под готовые регионы с их ступенчатой детализацией.

    Клиенты забирают плитки с нашего прокси, поэтому внешний источник
    отрабатывает это один раз, а не на каждого пользователя. Прогреваются
    оба стиля: тему на карте переключают на ходу, и в тёмной регион должен
    работать так же, как в светлой.
    """
    cache_root = _cache_root()
    styles = [style] if style else sorted(TILE_SOURCES)
    region_ids = [region] if region else sorted(REGIONS)

    planned = sum(region_tile_count(REGIONS[r]) for r in region_ids) * len(styles)
    # Пауза между плитками — не формальность: без неё источник банит по
    # User-Agent, поэтому она и определяет длительность прогрева.
    eta_hours = planned * delay / max(1, workers) / 3600
    click.echo(f'К обработке: {planned:,} плиток '
               f'({", ".join(region_ids)}; стили: {", ".join(styles)})')
    click.echo(f'Одни только паузы займут ~{eta_hours:.1f} ч, '
               f'реальное время больше на время запросов.')

    grand = {'ok': 0, 'cached': 0, 'fail': 0}
    for region_id in region_ids:
        definition = REGIONS[region_id]
        click.echo(f'== {definition["title"]} ==')
        for current_style in styles:
            for layer in definition['layers']:
                z0, z1 = layer['min_zoom'], layer['max_zoom']
                click.echo(f'  {current_style}, слой z{z0}-{z1}...')
                stats = seed_tiles(cache_root, layer['bbox'], current_style, z0, z1,
                                   workers, delay,
                                   lambda i, s: click.echo(
                                       f'    {i:,}/{s["total"]:,} скачано={s["ok"]:,} '
                                       f'из кэша={s["cached"]:,} ошибок={s["fail"]:,}'))
                for key in grand:
                    grand[key] += stats[key]

    click.echo(f'Готово: скачано={grand["ok"]:,} было в кэше={grand["cached"]:,} '
               f'ошибок={grand["fail"]:,}')


@tiles_bp.cli.command('seed')
@click.option('--bbox', nargs=4, type=float, default=DEFAULT_BBOX,
              metavar='SOUTH WEST NORTH EAST',
              help='Границы района. По умолчанию Ташкент.')
@click.option('--style', type=click.Choice(sorted(TILE_SOURCES)), default='light')
@click.option('--min-zoom', type=int, default=10, show_default=True)
@click.option('--max-zoom', type=int, default=17, show_default=True,
              help='Выше 17 объём растёт вчетверо на каждый уровень.')
@click.option('--workers', type=int, default=4, show_default=True)
@click.option('--delay', type=float, default=0.05, show_default=True,
              help='Пауза после каждого тайла, секунды.')
def seed_command(**kwargs):
    """Заранее скачать тайлы для района, чтобы карта не ждала источник."""
    bbox = kwargs['bbox']
    style = kwargs['style']
    min_zoom, max_zoom = kwargs['min_zoom'], kwargs['max_zoom']

    if max_zoom > MAX_ZOOM:
        raise click.BadParameter(f'максимум {MAX_ZOOM}', param_hint='--max-zoom')

    total = sum(1 for _ in iter_tiles(bbox, min_zoom, max_zoom))
    click.echo(f'Тайлов к обработке: {total:,} стиль={style}')

    # Путь считаем здесь, пока контекст приложения есть: в потоки пула он
    # не передаётся, и current_app внутри work() был бы недоступен.
    cache_root = _cache_root()

    def progress(i, stats):
        click.echo(f'  {i:,}/{stats["total"]:,}  скачано={stats["ok"]:,} '
                   f'из кэша={stats["cached"]:,} ошибок={stats["fail"]:,}')

    stats = seed_tiles(cache_root, bbox, style, min_zoom, max_zoom,
                       kwargs['workers'], kwargs['delay'], progress)
    click.echo(f'Готово: скачано={stats["ok"]:,} было в кэше={stats["cached"]:,} '
               f'ошибок={stats["fail"]:,}')

    # Ручной прогон тоже засчитываем, чтобы автопрогрев не начинал заново.
    if stats['fail'] == 0:
        with open(os.path.join(cache_root, '.seed-done'), 'w') as fh:
            fh.write(_seed_signature(bbox, style, min_zoom, max_zoom))