# app/services/meeting_guard_service.py
"""Страж встреч: подчищает за менеджерами, которые не отмечают встречи.

Когда заявка переходит в «Сделку в работе», проверяем, была ли по ней
задача-встреча за последние три месяца. Если не было — ставим задачу
«Встреча в офисе» на менеджера сделки с датой перехода и присылаем ему
уведомление в CRM: закрыть её как состоявшуюся.

Почему так, а не иначе:

* Вебхуков у Macro нет, поэтому переход ловим опросом API: заявки,
  изменённые с прошлого опроса, в статусе «Сделка в работе». Витрина
  MacroData отстаёт примерно на час — по ней новые сделки видны поздно.
* Встречу ищем в двух местах. API отдаёт только активные задачи, а
  закрытые (то есть состоявшиеся) встречи есть только в витрине.
* Сразу состоявшейся задачу создать нельзя: у tasks/create нет ни статуса,
  ни результата, а методов закрыть задачу в API нет. Поэтому — открытая
  задача и уведомление менеджеру.
* Каждая сделка обрабатывается один раз — это держит журнал. Ошибки
  повторяются до трёх раз.
"""

import logging
from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy import text

from app.core.extensions import db
from app.models.automation_models import AutoMeetingLog, AutomationState
from . import macro_api_service as api

logger = logging.getLogger(__name__)

MEETING_TYPES = ('meeting', 'meeting_house')
FINAL_DECISIONS = ('created', 'has_meeting', 'before_enable', 'dry_run')
MAX_ATTEMPTS = 3
POLL_OVERLAP = timedelta(minutes=10)
# estateBuy/list без ids разрешает окно не больше 7 дней.
MAX_WINDOW = timedelta(days=7) - timedelta(minutes=5)
MAX_PAGES = 50

STATE_ENABLED_AT = 'meeting_guard.enabled_at'
STATE_LAST_POLL = 'meeting_guard.last_poll_at'


# --- Настройки ---

def _settings():
    config = current_app.config

    def ints(raw):
        return {int(x) for x in str(raw or '').replace(' ', '').split(',') if x.isdigit()}

    return {
        'enabled': bool(config.get('MEETING_GUARD_ENABLED')),
        'dry_run': bool(config.get('MEETING_GUARD_DRY_RUN')),
        'house_ids': ints(config.get('MEETING_GUARD_HOUSE_IDS')),
        'statuses': ints(config.get('MEETING_GUARD_STATUSES')) or {50},
        'lookback': timedelta(days=int(config.get('MEETING_GUARD_LOOKBACK_DAYS') or 90)),
        'types_id': int(config['MEETING_GUARD_TYPES_ID']) if str(config.get('MEETING_GUARD_TYPES_ID') or '').isdigit() else None,
        'assigner_id': int(config['MEETING_GUARD_ASSIGNER_ID']) if str(config.get('MEETING_GUARD_ASSIGNER_ID') or '').isdigit() else None,
    }


def _state(key):
    row = db.session.get(AutomationState, key)
    return datetime.fromisoformat(row.value) if row and row.value else None


def _set_state(key, value):
    row = db.session.get(AutomationState, key) or AutomationState(key=key)
    row.value = value.isoformat(timespec='seconds')
    db.session.add(row)


# --- Ответы API ---

def _unwrap(body):
    """Часть методов оборачивает ответ в data, часть — нет."""
    if isinstance(body, dict) and 'data' in body and len(body) <= 3:
        return body['data']
    return body


def _parse_time(value):
    """Дата из API в наивное локальное время — как в витрине."""
    if value in (None, ''):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value)
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed


def _iso(moment):
    return moment.astimezone().isoformat(timespec='seconds')


_cache = {}


MEETING_TYPE_NAME = 'встреча в офисе'


def _task_types(body):
    """Список типов из ответа справочника — массив или массив внутри объекта."""
    body = _unwrap(body)
    if isinstance(body, dict):
        for key in ('types', 'items', 'data', 'tasksTypes', 'tasks_types'):
            if isinstance(body.get(key), list):
                return body[key]
        return []
    return body if isinstance(body, list) else []


def _system_type(item):
    for key in ('system_type', 'systemType', 'type', 'system'):
        if item.get(key):
            return str(item[key]).strip().lower()
    return ''


def find_meeting_type(types):
    """Тип «Встреча в офисе» — с системным типом meeting.

    Решает системный тип, а не название: в справочнике бывают двойники вроде
    «встреча в офисе» с типом other. Такая задача не считается встречей ни в
    CRM, ни в витрине (tasks.custom_type), и воронка её не увидит. Название
    — только чтобы выбрать среди нескольких встреч и как последний шанс.
    """
    types = [t for t in types if isinstance(t, dict) and t.get('id')]

    def named(t):
        return str(t.get('name', '')).strip().lower() == MEETING_TYPE_NAME

    meetings = [t for t in types if _system_type(t) == 'meeting']
    if meetings:
        meetings.sort(key=lambda t: (not named(t), 'офис' not in str(t.get('name', '')).lower()))
        return int(meetings[0]['id'])
    # Системный тип не пришёл ни в каком поле — тогда по названию.
    if not any(_system_type(t) for t in types):
        by_name = [t for t in types if named(t)]
        if by_name:
            return int(by_name[0]['id'])
    return None


def meeting_types_id(settings):
    """Кастомный тип «Встреча в офисе» — из настроек или из справочника."""
    if settings['types_id']:
        return settings['types_id']
    if 'types_id' not in _cache:
        types = _task_types(api.call_raw('tasks/listTasksTypes', {}))
        found = find_meeting_type(types)
        if not found:
            names = ', '.join(f"{t.get('id')}: {t.get('name')}" for t in types if isinstance(t, dict))[:500]
            raise api.MacroApiError('В справочнике типов задач не найден тип «Встреча в офисе». '
                                    f'Есть: {names or "пусто"}. Задайте MEETING_GUARD_TYPES_ID.')
        _cache['types_id'] = found
    return _cache['types_id']


# --- Поиск сделок ---

def _modified_leads(since):
    """Заявки, изменённые после since, с активными задачами."""
    leads, cursor = [], None
    for _ in range(MAX_PAGES):
        payload = {'date_modified_from': _iso(since), 'include_tasks': True}
        if cursor:
            payload['from'] = cursor
        body = api.call_raw('estateBuy/list', payload)
        leads.extend(body.get('data') or [])
        cursor = (body.get('meta') or {}).get('next')
        if not cursor:
            break
    return leads


def _leads_by_ids(ids):
    leads = []
    ids = list(ids)
    for start in range(0, len(ids), 10):
        body = api.call_raw('estateBuy/list', {'ids': ids[start:start + 10], 'include_tasks': True})
        leads.extend(body.get('data') or [])
    return leads


def _deal(deal_id):
    body = api.call_raw('estateDeals/list', {'deal_ids': [int(deal_id)]})
    data = body.get('data') or []
    return data[0] if data else None


def _is_candidate(lead, settings):
    if lead.get('status') not in settings['statuses'] or not lead.get('dealId'):
        return False
    return not settings['house_ids'] or lead.get('sellParentId') in settings['house_ids']


# --- Проверка встреч ---

def _active_meeting(lead, since):
    """Активная задача-встреча по заявке, поставленная не раньше since."""
    for task in lead.get('tasks') or []:
        if task.get('systemType') not in MEETING_TYPES:
            continue
        try:
            info = _unwrap(api.call_raw('tasks/get', {'task_id': int(task['id'])}))
            info = info.get('task', info) if isinstance(info, dict) else {}
            added = _parse_time(info.get('date_added'))
        except api.MacroApiError:
            added = None
        # Дату не прочитали — считаем встречу найденной: лишняя задача
        # менеджеру хуже, чем пропущенная отметка.
        if added is None or added >= since:
            return int(task['id'])
    return None


def _closed_meeting(lead_id, since):
    """Задача-встреча по заявке в витрине — там есть и закрытые."""
    engine = db.engines['mysql_source']
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT id FROM tasks WHERE estate_id = :lead AND custom_type IN ('meeting', 'meeting_house') "
            "AND date_added >= :since ORDER BY id DESC LIMIT 1"),
            {'lead': int(lead_id), 'since': since.date()}).first()
    return int(row[0]) if row else None


def _moved_before(lead_id, moment, statuses):
    """Переход в «Сделку в работе» по витрине был раньше moment."""
    engine = db.engines['mysql_source']
    codes = sorted(statuses)
    placeholders = ', '.join(f':s{i}' for i in range(len(codes)))
    params = {'lead': int(lead_id), 'low': min(codes), **{f's{i}': c for i, c in enumerate(codes)}}
    with engine.connect() as conn:
        row = conn.execute(text(
            'SELECT MIN(log_date) FROM estate_buys_statuses_log '
            f'WHERE estate_buy_id = :lead AND status_to IN ({placeholders}) AND status_from < :low'),
            params).first()
    first = row[0] if row else None
    if isinstance(first, str):
        first = _parse_time(first)
    return bool(first and first < moment)


# --- Создание встречи ---

def _create_meeting(lead, manager_id, moved_at, settings):
    moved_text = moved_at.strftime('%d.%m.%Y %H:%M')
    lookback_days = settings['lookback'].days
    payload = {
        'manager_id': manager_id,
        'assigner_id': settings['assigner_id'] or manager_id,
        'type': 'other',
        'types_id': meeting_types_id(settings),
        'title': 'Встреча с клиентом — отметка по сделке',
        'description': (
            f'Заявка перешла в «Сделку в работе» {moved_text}, но встречи с клиентом '
            f'за последние {lookback_days} дней в CRM не отмечено. Задача поставлена '
            'автоматически: если встреча была — закройте её как состоявшуюся.'),
        'date_finish': _iso(moved_at),
        'estate_id': int(lead['id']),
    }
    body = _unwrap(api.call_raw('tasks/create', payload))
    task_id = body.get('task_id') if isinstance(body, dict) else None
    if not task_id:
        raise api.MacroApiError(f'tasks/create: в ответе нет task_id ({str(body)[:200]})')
    return int(task_id)


def _notify(manager_id, task_id, moved_at):
    api.call_raw('notifications/create', {
        'userId': manager_id,
        'subject': 'Отметьте встречу по сделке',
        'description': (f'Сделка перешла в работу {moved_at:%d.%m.%Y}, а встреча с клиентом не отмечена. '
                        'Поставили задачу-встречу — закройте её как состоявшуюся.'),
        'entity': 'task',
        'entityId': task_id,
        'deliverToMessengers': True,
    })


# --- Обработка сделки ---

def _handle(lead, settings, enabled_at, log=None):
    lead_id, deal_id = int(lead['id']), int(lead['dealId'])
    log = log or AutoMeetingLog.query.filter_by(estate_buy_id=lead_id, deal_id=deal_id).first()
    if log and (log.decision in FINAL_DECISIONS or log.attempts >= MAX_ATTEMPTS):
        return None
    log = log or AutoMeetingLog(estate_buy_id=lead_id, deal_id=deal_id, attempts=0)
    log.house_id = lead.get('sellParentId')
    log.attempts = (log.attempts or 0) + 1
    log.error = None

    try:
        deal = _deal(deal_id) or {}
        manager_id = (deal.get('manager') or {}).get('id') or lead.get('managerId')
        moved_at = _parse_time(deal.get('dateModified')) or _parse_time(lead.get('dateModified')) or datetime.now()
        log.manager_id, log.moved_at = manager_id, moved_at

        # Только новые переходы: сделка, ушедшая в работу до включения,
        # могла просто измениться (правка договора) — её не трогаем.
        if moved_at < enabled_at or _moved_before(lead_id, enabled_at, settings['statuses']):
            log.decision = 'before_enable'
        else:
            since = moved_at - settings['lookback']
            found = _active_meeting(lead, since) or _closed_meeting(lead_id, since)
            if found:
                log.decision, log.found_task_id = 'has_meeting', found
            elif not manager_id:
                raise api.MacroApiError('у сделки нет менеджера')
            elif settings['dry_run']:
                log.decision = 'dry_run'
            else:
                log.task_id = _create_meeting(lead, manager_id, moved_at, settings)
                log.decision = 'created'
                try:
                    _notify(manager_id, log.task_id, moved_at)
                    log.notified = True
                except api.MacroApiError as e:
                    # Задача уже создана — повторять её нельзя, только отметить.
                    log.error = f'уведомление не отправлено: {e}'
    except Exception as e:  # noqa: BLE001 — любую ошибку пишем в журнал и повторим
        log.decision, log.error = 'error', str(e)[:1000]
        logger.warning('[MEETING GUARD] заявка %s, сделка %s: %s', lead_id, deal_id, e)

    db.session.add(log)
    db.session.commit()
    return log.decision


def run_once(now=None):
    """Один проход: новые сделки и повтор ошибок. Возвращает счётчики."""
    settings = _settings()
    if not settings['enabled']:
        return {'status': 'выключен (MEETING_GUARD_ENABLED)'}
    if not api.is_configured():
        return {'status': 'нет доступа к Macro API (MACRO_API_URL/MACRO_API_TOKEN)'}

    now = now or datetime.now()
    enabled_at = _state(STATE_ENABLED_AT)
    if enabled_at is None:
        # Первый запуск: всё, что было раньше, — прошлые переходы.
        enabled_at = now
        _set_state(STATE_ENABLED_AT, now)
        _set_state(STATE_LAST_POLL, now)
        db.session.commit()
        return {'status': f'включён с {now:%d.%m.%Y %H:%M}, обрабатываются переходы с этого момента'}

    # Тип задачи — настройка, а не свойство сделки: если его не найти, ни
    # одну встречу не создать. Останавливаем проход целиком и не тратим
    # попытки сделок — иначе они сгорят на ошибке конфигурации.
    if not settings['dry_run']:
        try:
            meeting_types_id(settings)
        except api.MacroApiError as e:
            logger.warning('[MEETING GUARD] %s', e)
            return {'status': f'не определён тип задачи: {e}'}

    last_poll = _state(STATE_LAST_POLL) or enabled_at
    since = max(last_poll - POLL_OVERLAP, now - MAX_WINDOW)

    counts, handled = {}, set()
    for lead in _modified_leads(since):
        if _is_candidate(lead, settings):
            handled.add(int(lead['id']))
            decision = _handle(lead, settings, enabled_at)
            if decision:
                counts[decision] = counts.get(decision, 0) + 1

    # Ошибки прошлых проходов. Упавшее в этом проходе ждёт следующего —
    # иначе три попытки сгорали бы за один сбой Macro.
    retry = [log for log in AutoMeetingLog.query.filter(
        AutoMeetingLog.decision == 'error', AutoMeetingLog.attempts < MAX_ATTEMPTS).all()
        if log.estate_buy_id not in handled]
    if retry:
        by_lead = {log.estate_buy_id: log for log in retry}
        for lead in _leads_by_ids(by_lead):
            log = by_lead.get(int(lead['id']))
            if log and lead.get('dealId') and int(lead['dealId']) == log.deal_id:
                decision = _handle(lead, settings, enabled_at, log=log)
                if decision:
                    counts[f'повтор:{decision}'] = counts.get(f'повтор:{decision}', 0) + 1

    _set_state(STATE_LAST_POLL, now)
    db.session.commit()
    return {'status': 'ok', 'since': since.strftime('%d.%m.%Y %H:%M'), **counts}


def reset_errors():
    """Вернуть сделки с ошибкой в очередь — после исправления настроек."""
    rows = AutoMeetingLog.query.filter_by(decision='error').all()
    for row in rows:
        row.attempts = 0
    db.session.commit()
    return len(rows)


def check_lead(lead_id):
    """Разбор одной заявки без записи в CRM и журнал — для проверки настроек."""
    settings = _settings()
    leads = _leads_by_ids([int(lead_id)])
    if not leads:
        return {'lead': lead_id, 'result': 'заявка не найдена в API'}
    lead = leads[0]
    report = {
        'lead': lead_id, 'status': lead.get('status'), 'deal_id': lead.get('dealId'),
        'house_id': lead.get('sellParentId'), 'candidate': _is_candidate(lead, settings),
        'active_tasks': lead.get('tasks'),
    }
    if lead.get('dealId'):
        deal = _deal(lead['dealId']) or {}
        moved_at = _parse_time(deal.get('dateModified')) or datetime.now()
        since = moved_at - settings['lookback']
        report.update({
            'deal_status': deal.get('statusName'), 'manager': deal.get('manager'),
            'moved_at': moved_at.strftime('%d.%m.%Y %H:%M'),
            'active_meeting': _active_meeting(lead, since),
            'closed_meeting': _closed_meeting(lead['id'], since),
        })
        report['would_create'] = bool(report['candidate'] and not report['active_meeting']
                                      and not report['closed_meeting'])
    return report
