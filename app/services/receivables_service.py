# app/services/receivables_service.py
"""Дебиторка менеджера: что клиенты должны заплатить по его сделкам.

Источник — график платежей в Macro: строки finances со статусом «К оплате».
Срок платежа лежит в date_to, поэтому просрочка и ближайшие платежи считаются
от сегодняшней даты, а не от даты создания операции.
"""

from datetime import date, timedelta

from flask import current_app
from sqlalchemy.orm import joinedload

from ..core.dates import to_date
from ..core.db_utils import get_mysql_session
from app.models.estate_models import EstateDeal, EstateHouse, EstateSell
from app.models.finance_models import FinanceOperation

# Статус строки графика, которая ещё не оплачена.
PENDING_STATUS = 'К оплате'
# Горизонт «ближайшей» дебиторки по умолчанию.
DEFAULT_HORIZON_DAYS = 30


def deal_url(deal_id):
    """Ссылка на сделку в CRM. Пустой шаблон -> ссылки нет."""
    template = current_app.config.get('CRM_DEAL_URL') or ''
    if not template or not deal_id:
        return None
    return template.replace('{deal_id}', str(deal_id))


def _row(operation, deal, sell, house, today):
    # date_to приходит из MySQL как datetime: без приведения вычитание из date
    # роняет отчёт с TypeError.
    due_date = to_date(operation.date_to)
    days = (due_date - today).days if due_date else None
    return {
        'operation_id': operation.id,
        'deal_id': deal.id if deal else None,
        'agreement_number': deal.agreement_number if deal else None,
        'complex_name': house.complex_name if house else None,
        'house': house.geo_house if house else None,
        'flat_number': sell.geo_flatnum if sell else None,
        'property_type': sell.estate_sell_category if sell else None,
        'amount': operation.summa or 0.0,
        'due_date': due_date,
        'payment_type': operation.payment_type,
        # Отрицательное — просрочено на столько дней, положительное — осталось.
        'days': days,
        'days_overdue': -days if days is not None and days < 0 else 0,
        'crm_url': deal_url(deal.id if deal else None),
    }


def get_manager_receivables(manager_id, horizon_days=DEFAULT_HORIZON_DAYS, today=None):
    """Просроченная и ближайшая дебиторка по сделкам менеджера.

    Менеджер определяется по сделке, а не по строке платежа: в графике
    ответственный может быть не проставлен, а сделка всегда за кем-то закреплена.
    """
    empty = {'overdue': [], 'upcoming': [], 'totals': {'overdue': 0.0, 'upcoming': 0.0},
             'horizon_days': horizon_days}
    if not manager_id:
        return empty

    today = today or date.today()
    horizon = today + timedelta(days=horizon_days)
    mysql_session = get_mysql_session()

    rows = mysql_session.query(FinanceOperation, EstateDeal, EstateSell, EstateHouse).join(
        EstateSell, FinanceOperation.estate_sell_id == EstateSell.id
    ).join(
        EstateDeal, EstateDeal.estate_sell_id == EstateSell.id
    ).join(
        EstateHouse, EstateSell.house_id == EstateHouse.id
    ).filter(
        FinanceOperation.status_name == PENDING_STATUS,
        FinanceOperation.date_to.isnot(None),
        # Граница — начало следующего дня: у датой-временем платёж последнего
        # дня горизонта иначе отсекается по времени суток.
        FinanceOperation.date_to < horizon + timedelta(days=1),
        EstateDeal.deal_manager_id == manager_id,
    ).order_by(FinanceOperation.date_to.asc()).all()

    overdue, upcoming = [], []
    for operation, deal, sell, house in rows:
        row = _row(operation, deal, sell, house, today)
        # Считаем по уже приведённой дате из строки: сравнивать date_to с date
        # напрямую нельзя по той же причине, что и вычитать.
        (overdue if row['days'] is not None and row['days'] < 0 else upcoming).append(row)

    return {
        'overdue': overdue,
        'upcoming': upcoming,
        'totals': {
            'overdue': sum(r['amount'] for r in overdue),
            'upcoming': sum(r['amount'] for r in upcoming),
        },
        'horizon_days': horizon_days,
    }
