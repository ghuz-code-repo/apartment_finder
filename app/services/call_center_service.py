# app/services/call_center_service.py
"""Аналитика колл-центра: динамика обзвона, подбора и встреч.

Три показателя берутся из трёх разных таблиц витрины, и это не случайность:

* обзвон — таблица calls, по дате звонка. Внутренние и скрытые звонки не
  считаются: это разговоры между сотрудниками, а не работа с клиентами;
* подбор — переходы в статус «Подбор» в логе статусов, а не текущий статус
  заявки: за период важно, сколько подборов сделали, даже если заявка потом
  ушла дальше;
* встречи — отчёты о встречах, а не подстатус заявки. Отчёт и есть факт
  встречи, и у него своя дата учёта.

Раскладка по периодам общая с отчётом «Контрактация и поступления»: функции
периодов лежат там, дублировать их незачем.
"""

from datetime import datetime, timedelta

from sqlalchemy import func

from ..core.dates import to_date
from ..core.db_utils import get_mysql_session
from app.models.auth_models import SalesManager
from app.models.estate_models import EstateHouse
from app.models.funnel_models import EstateBuy, EstateBuysStatusLog
from app.models.marketing_models import Call, EstateMeeting
from .contracting_income_service import (GRANULARITIES, build_periods, period_label,
                                         period_start)

DEFAULT_GRANULARITY = 'day'

# Статус «Подбор» в витрине.
STATUS_PODBOR = 'Подбор'
# Внутренние звонки — разговоры сотрудников между собой.
CALL_DIRECTIONS = ('in', 'out')

# Конечные статусы: до них заявку «ведут», дальше она закрыта.
CLOSING_STATUSES = ('Сделка проведена', 'Сделка в работе', 'Отказ', 'Нецелевой')


def _house_ids_for_complexes(complexes):
    """id домов выбранных ЖК. None — фильтра по проекту нет."""
    if not complexes:
        return None
    rows = get_mysql_session().query(EstateHouse.id).filter(
        EstateHouse.complex_name.in_(complexes)
    ).all()
    return [row[0] for row in rows]


def get_filter_options():
    """Списки для фильтров: проекты и менеджеры."""
    mysql_session = get_mysql_session()
    complexes = [row[0] for row in mysql_session.query(EstateHouse.complex_name)
                 .filter(EstateHouse.complex_name.isnot(None))
                 .distinct().order_by(EstateHouse.complex_name).all()]
    managers = mysql_session.query(SalesManager).order_by(SalesManager.full_name).all()
    return {'complexes': complexes, 'managers': managers}


# --- Ряды динамики ---

def _call_rows(start_date, end_date, manager_ids, house_ids):
    """Звонки интервала: одна дата на звонок."""
    query = get_mysql_session().query(Call.call_date).filter(
        Call.call_date.isnot(None),
        Call.call_date >= start_date,
        Call.call_date < end_date + timedelta(days=1),
        Call.direction.in_(CALL_DIRECTIONS),
    )

    # Скрытые звонки витрина помечает сама — в отчёт они не идут.
    query = query.filter((Call.is_hidden.is_(None)) | (Call.is_hidden == 0))

    if manager_ids:
        query = query.filter(Call.manager_id.in_(manager_ids))
    if house_ids is not None:
        # У звонка своего дома нет — проект берём у заявки, к которой он привязан.
        query = query.join(EstateBuy, Call.estate_id == EstateBuy.id).filter(
            EstateBuy.house_id.in_(house_ids))

    return [row[0] for row in query.all()]


def _selection_rows(start_date, end_date, manager_ids, house_ids):
    """Переходы в «Подбор» за интервал."""
    query = get_mysql_session().query(EstateBuysStatusLog.log_date).filter(
        EstateBuysStatusLog.log_date.isnot(None),
        EstateBuysStatusLog.log_date >= start_date,
        EstateBuysStatusLog.log_date < end_date + timedelta(days=1),
        EstateBuysStatusLog.status_to_name == STATUS_PODBOR,
    )

    if manager_ids:
        query = query.filter(EstateBuysStatusLog.manager_id.in_(manager_ids))
    if house_ids is not None:
        query = query.join(EstateBuy, EstateBuysStatusLog.estate_buy_id == EstateBuy.id).filter(
            EstateBuy.house_id.in_(house_ids))

    return [row[0] for row in query.all()]


def _meeting_rows(start_date, end_date, manager_ids, house_ids, only_held=False):
    """Встречи интервала по дате учёта."""
    query = get_mysql_session().query(EstateMeeting.meeting_date).filter(
        EstateMeeting.meeting_date.isnot(None),
        EstateMeeting.meeting_date >= start_date,
        EstateMeeting.meeting_date < end_date + timedelta(days=1),
    )

    if only_held:
        # Несостоявшиеся встречи витрина помечает признаком no_meeting.
        query = query.filter((EstateMeeting.no_meeting.is_(None)) | (EstateMeeting.no_meeting == 0))
    if manager_ids:
        query = query.filter(EstateMeeting.manager_id.in_(manager_ids))
    if house_ids is not None:
        query = query.filter(EstateMeeting.house_id.in_(house_ids))

    return [row[0] for row in query.all()]


def get_dynamics(start_date, end_date, granularity=DEFAULT_GRANULARITY,
                 manager_ids=None, complexes=None):
    """Обзвон, подбор и встречи по периодам интервала."""
    if granularity not in dict(GRANULARITIES):
        granularity = DEFAULT_GRANULARITY

    house_ids = _house_ids_for_complexes(complexes)
    # Пустой список домов означает, что под фильтр не попал ни один проект:
    # считать «как будто фильтра нет» было бы враньём.
    if house_ids is not None and not house_ids:
        house_ids = [0]

    periods = build_periods(start_date, end_date, granularity)
    buckets = {p: {'calls': 0, 'selections': 0, 'meetings': 0} for p in periods}

    series = (
        ('calls', _call_rows(start_date, end_date, manager_ids, house_ids)),
        ('selections', _selection_rows(start_date, end_date, manager_ids, house_ids)),
        ('meetings', _meeting_rows(start_date, end_date, manager_ids, house_ids)),
    )
    for key, rows in series:
        for raw_date in rows:
            day = to_date(raw_date)
            bucket = buckets.get(period_start(day, granularity)) if day else None
            if bucket is not None:
                bucket[key] += 1

    rows = [{'period': p.isoformat(), 'label': period_label(p, granularity), **buckets[p]}
            for p in periods]

    return {
        'rows': rows,
        'granularity': granularity,
        'totals': {
            'calls': sum(r['calls'] for r in rows),
            'selections': sum(r['selections'] for r in rows),
            'meetings': sum(r['meetings'] for r in rows),
        },
    }


# --- Заявки по менеджерам ---

def _as_datetime(value):
    """Дата из витрины к datetime: вычитать date из datetime нельзя."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    day = to_date(value)
    return datetime(day.year, day.month, day.day) if day else None


def _first_action_dates(buy_ids):
    """Первое действие по каждой заявке — самая ранняя запись в логе статусов."""
    if not buy_ids:
        return {}

    rows = get_mysql_session().query(
        EstateBuysStatusLog.estate_buy_id,
        func.min(EstateBuysStatusLog.log_date)
    ).filter(
        EstateBuysStatusLog.estate_buy_id.in_(buy_ids),
        EstateBuysStatusLog.log_date.isnot(None),
    ).group_by(EstateBuysStatusLog.estate_buy_id).all()

    return {buy_id: first for buy_id, first in rows}


def get_manager_stats(start_date, end_date, manager_ids=None, complexes=None):
    """Обработанные заявки и среднее время до первого действия по менеджерам.

    Заявка относится к менеджеру колл-центра, а если он не проставлен — к
    менеджеру заявки: в витрине первое поле заполняется не всегда, и без
    подмены такие заявки просто исчезли бы из отчёта.

    Время обработки считается от создания заявки до первой записи в логе
    статусов: это скорость реакции на новую заявку.
    """
    mysql_session = get_mysql_session()
    house_ids = _house_ids_for_complexes(complexes)
    if house_ids is not None and not house_ids:
        house_ids = [0]

    query = mysql_session.query(
        EstateBuy.id,
        EstateBuy.created_at,
        func.coalesce(EstateBuy.call_center_manager_id, EstateBuy.manager_id).label('manager_id'),
    ).filter(
        EstateBuy.created_at.isnot(None),
        EstateBuy.created_at >= start_date,
        EstateBuy.created_at < end_date + timedelta(days=1),
    )

    if manager_ids:
        query = query.filter(
            func.coalesce(EstateBuy.call_center_manager_id, EstateBuy.manager_id).in_(manager_ids))
    if house_ids is not None:
        query = query.filter(EstateBuy.house_id.in_(house_ids))

    leads = query.all()
    if not leads:
        return {'rows': [], 'totals': {'leads': 0, 'processed': 0, 'avg_hours': None}}

    first_actions = _first_action_dates([lead.id for lead in leads])

    names = {m.id: m.full_name for m in mysql_session.query(SalesManager).all()}
    stats = {}
    for lead in leads:
        row = stats.setdefault(lead.manager_id, {
            'manager_id': lead.manager_id,
            'manager_name': names.get(lead.manager_id) or 'Не указан',
            'leads': 0,
            'processed': 0,
            '_hours': [],
        })
        row['leads'] += 1

        first = _as_datetime(first_actions.get(lead.id))
        created = _as_datetime(lead.created_at)
        if not first or not created:
            continue

        row['processed'] += 1
        delta = (first - created).total_seconds() / 3600
        # Отрицательная разница означает расхождение дат в источнике —
        # такие строки в среднее не берём, иначе оно уедет в минус.
        if delta >= 0:
            row['_hours'].append(delta)

    rows = []
    for row in stats.values():
        hours = row.pop('_hours')
        row['avg_hours'] = round(sum(hours) / len(hours), 1) if hours else None
        rows.append(row)

    rows.sort(key=lambda r: (-r['leads'], r['manager_name']))

    all_hours = [r['avg_hours'] for r in rows if r['avg_hours'] is not None]
    return {
        'rows': rows,
        'totals': {
            'leads': sum(r['leads'] for r in rows),
            'processed': sum(r['processed'] for r in rows),
            'avg_hours': round(sum(all_hours) / len(all_hours), 1) if all_hours else None,
        },
    }
