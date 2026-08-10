from datetime import datetime, date
from sqlalchemy import func, extract, desc
from app.core.db_utils import get_mysql_session, get_default_session
from app.models.estate_models import EstateDeal, EstateSell, EstateHouse
from app.models.finance_models import FinanceOperation
from app.models.registry_models import CancellationRegistry, DealRegistry, RegistryType
from app.models.auth_models import SalesManager
from app.models.planning_models import map_mysql_key_to_russian_value
import pandas as pd


def get_quarter_dates(year, quarter):
    quarters = {
        1: (date(year, 1, 1), date(year, 3, 31)),
        2: (date(year, 4, 1), date(year, 6, 30)),
        3: (date(year, 7, 1), date(year, 9, 30)),
        4: (date(year, 10, 1), date(year, 12, 31))
    }
    return quarters.get(quarter)


def get_quarterly_analytics(complex_name, year, quarter):
    mysql_session = get_mysql_session()
    local_session = get_default_session()
    start_date, end_date = get_quarter_dates(year, quarter)

    # 1. Темпы продаж по типам недвижимости (MySQL -> MySQL, OK)
    sales_query = mysql_session.query(
        EstateSell.estate_sell_category,
        extract('month', EstateDeal.agreement_date).label('month'),
        func.count(EstateDeal.id).label('count')
    ).join(EstateSell, EstateDeal.estate_sell_id == EstateSell.id) \
        .join(EstateHouse, EstateSell.house_id == EstateHouse.id) \
        .filter(
        EstateHouse.complex_name == complex_name,
        EstateDeal.agreement_date.between(start_date, end_date),
        EstateDeal.deal_status_name.in_(["Сделка в работе", "Сделка проведена"])
    ).group_by(EstateSell.estate_sell_category, 'month').all()

    sales_pace = {}
    for cat, month, count in sales_query:
        ru_cat = map_mysql_key_to_russian_value(cat)
        if ru_cat not in sales_pace:
            sales_pace[ru_cat] = [0, 0, 0]
        idx = int(month) - ((quarter - 1) * 3 + 1)
        if 0 <= idx < 3:
            sales_pace[ru_cat][idx] = count

    # 2. Лучшие менеджеры (MySQL -> MySQL, OK)
    top_managers = mysql_session.query(
        SalesManager.full_name.label('manager_name'),
        func.count(EstateDeal.id).label('deals_count'),
        func.sum(EstateDeal.deal_sum).label('total_sum')
    ).join(EstateSell, EstateDeal.estate_sell_id == EstateSell.id) \
        .join(EstateHouse, EstateSell.house_id == EstateHouse.id) \
        .join(SalesManager, EstateDeal.deal_manager_id == SalesManager.id) \
        .filter(
        EstateHouse.complex_name == complex_name,
        EstateDeal.agreement_date.between(start_date, end_date),
        EstateDeal.deal_status_name.in_(["Сделка в работе", "Сделка проведена"])
    ).group_by(SalesManager.full_name) \
        .order_by(desc('deals_count')).limit(5).all()

    # 3. Аналитика предпочтений (MySQL -> MySQL, OK)
    trends_query = mysql_session.query(
        EstateSell.estate_area, EstateSell.estate_floor, EstateSell.estate_rooms
    ).join(EstateDeal).join(EstateHouse) \
        .filter(
        EstateHouse.complex_name == complex_name,
        EstateDeal.agreement_date.between(start_date, end_date),
        EstateDeal.deal_status_name.in_(["Сделка в работе", "Сделка проведена"])
    ).all()

    df_trends = pd.DataFrame(
        [{'area': t.estate_area, 'floor': t.estate_floor, 'rooms': t.estate_rooms} for t in trends_query])
    trends = {
        'avg_area': round(df_trends['area'].mean(), 2) if not df_trends.empty else 0,
        'popular_floor': int(df_trends['floor'].mode()[0]) if not df_trends.empty else 0,
        'popular_rooms': int(df_trends['rooms'].mode()[0]) if not df_trends.empty else 0
    }

    # 4. Итоги и задолженность
    total_sold = len(trends_query)

    # Расторжения (SQLite, фильтрация по сохраненному complex_name, OK)
    cancellations_count = local_session.query(CancellationRegistry).filter(
        CancellationRegistry.complex_name == complex_name,
        CancellationRegistry.created_at.between(start_date, end_date)
    ).count()

    # Дебиторка (MySQL -> MySQL, OK)
    debt_query = mysql_session.query(func.sum(FinanceOperation.summa)).join(EstateSell).join(EstateHouse) \
                     .filter(
        EstateHouse.complex_name == complex_name,
        FinanceOperation.status_name == "К оплате",
        FinanceOperation.date_to <= date.today()
    ).scalar() or 0

    # 5. Виды оплаты (MySQL -> MySQL, OK)
    payment_query = mysql_session.query(
        EstateDeal.deal_program_name, func.count(EstateDeal.id)
    ).join(EstateSell).join(EstateHouse) \
        .filter(
        EstateHouse.complex_name == complex_name,
        EstateDeal.agreement_date.between(start_date, end_date),
        EstateDeal.deal_status_name.in_(["Сделка в работе", "Сделка проведена"])
    ).group_by(EstateDeal.deal_program_name).all()
    payment_methods = {(name or "Стандарт"): count for name, count in payment_query}

    # 6. Спец сделки (ИСПРАВЛЕНО: Двухэтапный запрос для обхода cross-db join)
    # Шаг А: Получаем ID всех объектов этого ЖК из MySQL
    complex_sell_ids = [r[0] for r in mysql_session.query(EstateSell.id).join(EstateHouse).filter(
        EstateHouse.complex_name == complex_name
    ).all()]

    # Шаг Б: Считаем спец. сделки в SQLite, фильтруя по списку ID
    special_deals_query = local_session.query(
        DealRegistry.registry_type, func.count(DealRegistry.id)
    ).filter(
        DealRegistry.estate_sell_id.in_(complex_sell_ids),
        DealRegistry.created_at.between(start_date, end_date)
    ).group_by(DealRegistry.registry_type).all()

    special_deals = {dt.value: count for dt, count in special_deals_query}

    # 7. Неплательщики (MySQL -> MySQL, OK)
    top_debtors = mysql_session.query(
        EstateDeal.id.label('deal_id'), func.sum(FinanceOperation.summa).label('debt')
    ).join(EstateSell, EstateDeal.estate_sell_id == EstateSell.id) \
        .join(FinanceOperation, EstateSell.id == FinanceOperation.estate_sell_id) \
        .join(EstateHouse, EstateSell.house_id == EstateHouse.id) \
        .filter(
        EstateHouse.complex_name == complex_name,
        FinanceOperation.status_name == "К оплате",
        FinanceOperation.date_to <= date.today()
    ).group_by(EstateDeal.id).order_by(desc('debt')).limit(10).all()

    return {
        'sales_pace': sales_pace,
        'top_managers': top_managers,
        'trends': trends,
        'totals': {'sold': total_sold, 'cancellations': cancellations_count, 'debt': debt_query},
        'payment_methods': payment_methods,
        'special_deals': special_deals,
        'top_debtors': top_debtors
    }