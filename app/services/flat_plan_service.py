# app/services/flat_plan_service.py
"""Планировки квартир: получение из Macro API и кэш.

Планировка — свойство типа квартиры, а не конкретного объекта: в ЖК десяток
типов на сотни квартир, и файлы у них одни и те же. Поэтому кэш двухуровневый:
ответ API лежит в planning_db по estateId, а сами картинки — на диске по хэшу
URL, так что все квартиры одного типа делят один файл.
"""
import json
import logging
from datetime import datetime, timedelta, timezone

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..core.db_utils import get_planning_session
from ..models.planning_models import FlatPlanCache
from . import macro_api_service
from .macro_api_service import MacroApiError

logger = logging.getLogger(__name__)

EMPTY_RESULT = {'plan_name': None, 'files': [], 'error': None}

# Планировки меняются крайне редко — держим долго.
CACHE_TTL = timedelta(days=7)
# После неудачи не ходим в Macro снова хотя бы час: это защищает и от лимита,
# и от того, что у квартиры планировки просто нет.
NEGATIVE_TTL = timedelta(hours=1)


def _now():
    return datetime.now(timezone.utc)


def _is_fresh(entry):
    if entry.fetched_at is None:
        return False
    fetched_at = entry.fetched_at
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    ttl = NEGATIVE_TTL if entry.error else CACHE_TTL
    return _now() - fetched_at < ttl


def _normalize_files(raw_files):
    """Оставляет от ответа Macro только то, что нужно шаблону."""
    files = []
    for item in raw_files or []:
        if not isinstance(item, dict):
            continue
        url = (item.get('url') or '').strip()
        if not url:
            continue
        files.append({
            'title': (item.get('title') or 'Планировка').strip(),
            'url': url,
            'thumb_url': (item.get('thumbUrl') or '').strip() or None,
        })
    return files


def _store(session, estate_id, plan_name, files, error):
    entry = session.get(FlatPlanCache, estate_id) or FlatPlanCache(estate_id=estate_id)
    entry.plan_name = plan_name
    entry.files_json = json.dumps(files, ensure_ascii=False)
    entry.error = error[:500] if error else None
    entry.fetched_at = _now()
    session.add(entry)
    session.commit()
    return entry


def _as_result(entry):
    try:
        files = json.loads(entry.files_json or '[]')
    except ValueError:
        files = []
    return {'plan_name': entry.plan_name, 'files': files, 'error': entry.error}


def get_flat_plans(estate_id, force_refresh=False):
    """Планировки квартиры: {'plan_name', 'files': [{title, url, thumb_url}], 'error'}.

    Никогда не бросает исключений — страница объекта не должна падать из-за
    недоступности чужого сервиса.
    """
    estate_id = int(estate_id)

    if not macro_api_service.is_configured():
        # Интеграция не настроена — отдаём пустой результат, не трогая БД:
        # карточка объекта не должна зависеть от таблицы кэша, пока Macro
        # вообще не подключён.
        return EMPTY_RESULT

    session = get_planning_session()
    try:
        entry = session.get(FlatPlanCache, estate_id)
    except SQLAlchemyError as exc:
        # Таблицы кэша ещё нет (например, между обновлением кода и стартом
        # приложения) — работаем без неё, страница важнее планировки.
        logger.warning('[PLANS] Кэш планировок недоступен: %s', exc)
        session.rollback()
        return EMPTY_RESULT

    if entry is not None and not force_refresh and _is_fresh(entry):
        return _as_result(entry)

    try:
        data = macro_api_service.get_flat_plans(estate_id)
        plan_name, files, error = data.get('planName'), _normalize_files(data.get('files')), None
    except MacroApiError as exc:
        logger.warning('[PLANS] Планировка %s не получена: %s', estate_id, exc)
        if entry is not None and not entry.error:
            # Протухший, но валидный кэш лучше пустоты.
            return _as_result(entry)
        plan_name, files, error = None, [], str(exc)

    result = {'plan_name': plan_name, 'files': files, 'error': error}
    try:
        _store(session, estate_id, plan_name, files, error)
    except SQLAlchemyError as exc:
        # Не смогли закэшировать — отдаём то, что уже получили от Macro.
        logger.warning('[PLANS] Кэш планировки %s не сохранён: %s', estate_id, exc)
        session.rollback()
    return result


def get_file_url(estate_id, index):
    """Абсолютный URL файла планировки по его номеру в кэше.

    Обращение идёт по индексу, а не по URL из запроса: так наш прокси не
    превращается в открытый ретранслятор чужих адресов.
    """
    result = get_flat_plans(estate_id)
    files = result.get('files') or []
    if index < 0 or index >= len(files):
        return None
    return absolutize(files[index]['url'])


def absolutize(url):
    """Достраивает относительный путь Macro до абсолютного адреса."""
    if not url:
        return None
    if url.startswith(('http://', 'https://')):
        return url
    base = (current_app.config.get('MACRO_FILES_BASE_URL') or '').rstrip('/')
    if not base:
        return None
    return f'{base}/{url.lstrip("/")}'
