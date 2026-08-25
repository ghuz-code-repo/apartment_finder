# app/services/contracting_income_service.py
"""Отчёт «Контрактация и поступления» с произвольной детализацией.

Определения намеренно совпадают с план-фактом, иначе один и тот же месяц
показывал бы в двух отчётах разные суммы:

* контрактация — сделки в статусах «Сделка в работе» и «Сделка проведена»,
  дата берётся как coalesce(дата договора, предварительная дата);
* поступления — проведённые операции, без возвратов, брони и уступок.

Раскладку по периодам делаем в Python, а не в SQL: функции работы с датами
у MySQL и SQLite разные, а объём строк за разумный интервал невелик.
"""

from datetime import date, timedelta

from ..core.db_utils import get_mysql_session
from app.models.auth_models import SalesManager
from app.models.estate_models import EstateDeal, EstateHouse, EstateSell
from app.models.finance_models import FinanceOperation
from sqlalchemy import func

DEAL_STATUSES = ["Сделка в работе", "Сделка проведена"]
INCOME_STATUS = "Проведено"
# Возвраты и служебные операции поступлениями не считаются.
EXCLUDED_PAYMENT_TYPES = [
    "Возврат поступлений при отмене сделки",
    "Возврат при уменьшении стоимости",
    "безучпоступление",
    "Уступка права требования",
    "Бронь",
]

GRANULARITIES = (
    ('day', 'По дням'),
    ('week', 'По неделям'),
    ('month', 'По месяцам'),
    ('quarter', 'По кварталам'),
    ('year', 'По годам'),
)
DEFAULT_GRANULARITY = 'month'

MONTH_NAMES = {
    1: 'Янв', 2: 'Фев', 3: 'Мар', 4: 'Апр', 5: 'Май', 6: 'Июн',
    7: 'Июл', 8: 'Авг', 9: 'Сен', 10: 'Окт', 11: 'Ноя', 12: 'Дек',
}


# --- Периоды ---

def period_start(day, granularity):
    """Начало периода, в который попадает дата."""
    if granularity == 'day':
        return day
    if granularity == 'week':
        return day - timedelta(days=day.weekday())
    if granularity == 'quarter':
        return date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)
    if granularity == 'year':
        return date(day.year, 1, 1)
    return date(day.year, day.month, 1)


def next_period(start, granularity):
    """Начало следующего периода — для перебора шкалы без пропусков."""
    if granularity == 'day':
        return start + timedelta(days=1)
    if granularity == 'week':
        return start + timedelta(days=7)
    if granularity == 'year':
        return date(start.year + 1, 1, 1)

    step = 3 if granularity == 'quarter' else 1
    month = start.month + step
    year = start.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return date(year, month, 1)


def period_label(start, granularity):
    """Подпись периода для графика и таблицы."""
    if granularity == 'day':
        return start.strftime('%d.%m.%Y')
    if granularity == 'week':
        end = start + timedelta(days=6)
        return f"{start.strftime('%d.%m')}–{end.strftime('%d.%m.%Y')}"
    if granularity == 'quarter':
        return f"{(start.month - 1) // 3 + 1} кв. {start.year}"
    if granularity == 'year':
        return str(start.year)
    return f"{MONTH_NAMES[start.month]} {start.year}"


def build_periods(start_date, end_date, granularity):
    """Все периоды интервала по порядку, включая пустые."""
    periods = []
    cursor = period_start(start_date, granularity)
    while cursor <= end_date:
        periods.append(cursor)
        cursor = next_period(cursor, granularity)
    return periods


# --- Фильтры ---

def get_filter_options():
    """Списки ЖК и менеджеров для фильтров."""
    mysql_session = get_mysql_session()
    complexes = [row[0] for row in mysql_session.query(EstateHouse.complex_name)
                 .filter(EstateHouse.complex_name.isnot(None))
                 .distinct().order_by(EstateHouse.complex_name).all()]
    managers = mysql_session.query(SalesManager).order_by(SalesManager.full_name).all()
    return {'complexes': complexes, 'managers': managers}


# --- Данные ---

def _contracting_rows(start_date, end_date, complexes, manager_ids):
    """Сделки интервала: (дата, сумма)."""
    effective_date = func.coalesce(EstateDeal.agreement_date, EstateDeal.preliminary_date)
    query = get_mysql_session().query(
        effective_date.label('day'), EstateDeal.deal_sum
    ).select_from(EstateDeal).join(
        EstateSell, EstateDeal.estate_sell_id == EstateSell.id
    ).join(
        EstateHouse, EstateSell.house_id == EstateHouse.id
    ).filter(
        EstateDeal.deal_status_name.in_(DEAL_STATUSES),
        effective_date.isnot(None),
        effective_date >= start_date,
        effective_date <= end_date,
    )

    if complexes:
        query = query.filter(EstateHouse.complex_name.in_(complexes))
    if manager_ids:
        query = query.filter(EstateDeal.deal_manager_id.in_(manager_ids))

    return query.all()


def _income_rows(start_date, end_date, complexes, manager_ids):
    """Проведённые поступления интервала: (дата, сумма)."""
    query = get_mysql_session().query(
        FinanceOperation.date_added.label('day'), FinanceOperation.summa
    ).select_from(FinanceOperation).join(
        EstateSell, FinanceOperation.estate_sell_id == EstateSell.id
    ).join(
        EstateHouse, EstateSell.house_id == EstateHouse.id
    ).filter(
        FinanceOperation.status_name == INCOME_STATUS,
        FinanceOperation.date_added.isnot(None),
        FinanceOperation.date_added >= start_date,
        FinanceOperation.date_added <= end_date,
        FinanceOperation.payment_type.notin_(EXCLUDED_PAYMENT_TYPES),
    )

    if complexes:
        query = query.filter(EstateHouse.complex_name.in_(complexes))
    if manager_ids:
        # У поступления свой ответственный менеджер — он и отвечает за сбор
        # денег, поэтому фильтруем по нему, а не по менеджеру сделки.
        query = query.filter(FinanceOperation.manager_id.in_(manager_ids))

    return query.all()


def _as_date(value):
    """Из БД дата может прийти datetime или строкой — приводим к date."""
    if value is None:
        return None
    if isinstance(value, date) and not hasattr(value, 'hour'):
        return value
    if hasattr(value, 'date'):
        return value.date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def get_report_data(start_date, end_date, granularity=DEFAULT_GRANULARITY,
                    complexes=None, manager_ids=None):
    """Ряды контрактации и поступлений по периодам интервала."""
    if granularity not in dict(GRANULARITIES):
        granularity = DEFAULT_GRANULARITY

    periods = build_periods(start_date, end_date, granularity)
    buckets = {
        p: {'contracting_sum': 0.0, 'contracting_count': 0, 'income_sum': 0.0}
        for p in periods
    }

    for day, deal_sum in _contracting_rows(start_date, end_date, complexes, manager_ids):
        day = _as_date(day)
        bucket = buckets.get(period_start(day, granularity)) if day else None
        if bucket is None:
            continue
        bucket['contracting_sum'] += deal_sum or 0.0
        bucket['contracting_count'] += 1

    for day, summa in _income_rows(start_date, end_date, complexes, manager_ids):
        day = _as_date(day)
        bucket = buckets.get(period_start(day, granularity)) if day else None
        if bucket is None:
            continue
        bucket['income_sum'] += summa or 0.0

    rows = [
        {
            'period': p.isoformat(),
            'label': period_label(p, granularity),
            **buckets[p],
        }
        for p in periods
    ]

    return {
        'rows': rows,
        'granularity': granularity,
        'totals': {
            'contracting_sum': sum(r['contracting_sum'] for r in rows),
            'contracting_count': sum(r['contracting_count'] for r in rows),
            'income_sum': sum(r['income_sum'] for r in rows),
        },
    }
