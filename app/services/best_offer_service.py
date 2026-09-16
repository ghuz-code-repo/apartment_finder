# app/services/best_offer_service.py
"""Конструктор офера: проекты, остатки и подбор лучших лотов под критерии.

Каждый показатель офера привязан к конкретной квартире и сопровождается
ссылкой на её карточку в CRM. Это требование заказчика и оно же определило
устройство модуля: никаких усреднённых «цена от», только реальный лот, по
которому цифру можно проверить.

Цены и скидки считает pricing_service — тот же модуль, что и в КП. Если
считать здесь отдельно, оферы и коммерческие предложения со временем начнут
расходиться в цифрах.
"""

from flask import current_app

from ..core.db_utils import get_mysql_session, get_planning_session
from app.models import planning_models
from app.models.estate_models import EstateHouse, EstateSell
from app.models.planning_models import PaymentMethod
from . import pricing_service
from app.models.planning_models import map_mysql_key_to_russian_value

# Свободный остаток: статусы, в которых квартиру ещё можно предложить.
AVAILABLE_STATUSES = ("Маркетинговый резерв", "Подбор")
# Квартиры: офер строится по ним, коммерция и кладовые сюда не идут.
FLAT_CATEGORY = 'flat'


def flat_url(sell_id):
    """Ссылка на карточку квартиры в CRM. Пустой шаблон — ссылки нет."""
    template = current_app.config.get('CRM_FLAT_URL') or ''
    if not template or not sell_id:
        return None
    return template.replace('{sell_id}', str(sell_id))


def list_projects():
    """Активные проекты с остатком квартир."""
    mysql_session = get_mysql_session()
    rows = mysql_session.query(
        EstateHouse.complex_name,
        EstateSell.id,
        EstateSell.estate_price,
        EstateSell.estate_price_m2,
        EstateSell.estate_area,
    ).join(EstateHouse, EstateSell.house_id == EstateHouse.id).filter(
        EstateHouse.complex_name.isnot(None),
        EstateSell.estate_sell_category == FLAT_CATEGORY,
        EstateSell.estate_sell_status_name.in_(AVAILABLE_STATUSES),
    ).all()

    projects = {}
    for complex_name, _sell_id, price, price_m2, area in rows:
        project = projects.setdefault(complex_name, {
            'complex_name': complex_name,
            'flats': 0,
            'min_price': None,
            'min_price_m2': None,
            'min_area': None,
            'max_area': None,
        })
        project['flats'] += 1

        for key, value in (('min_price', price), ('min_price_m2', price_m2),
                           ('min_area', area)):
            if value and (project[key] is None or value < project[key]):
                project[key] = value
        if area and (project['max_area'] is None or area > project['max_area']):
            project['max_area'] = area

    return sorted(projects.values(), key=lambda p: p['complex_name'])


def get_project_discounts(complex_name):
    """Доступные скидки проекта по квартирам: код, название и потолок."""
    planning_session = get_planning_session()
    active_version = planning_session.query(planning_models.DiscountVersion).filter_by(
        is_active=True).first()
    if not active_version:
        return {}

    rows = planning_session.query(planning_models.Discount).filter_by(
        version_id=active_version.id,
        complex_name=complex_name,
        property_type=planning_models.PropertyType.FLAT,
    ).all()

    discounts = {}
    for row in rows:
        limits = [
            {'code': code, 'name': name,
             'max_percent': int(round((getattr(row, code) or 0) * 100))}
            for code, name in pricing_service.MANUAL_DISCOUNT_FIELDS
            if int(round((getattr(row, code) or 0) * 100)) > 0
        ]
        discounts[row.payment_method] = {
            'limits': limits,
            'cadastre_date': row.cadastre_date,
            'row': row,
        }
    return discounts


def _serialize_discount_row(row):
    """Строка матрицы в том виде, в каком её ждёт pricing_service."""
    return {
        'complex_name': row.complex_name,
        'property_type': row.property_type.value,
        'payment_method': row.payment_method.value,
        'mpp': row.mpp or 0.0, 'rop': row.rop or 0.0, 'kd': row.kd or 0.0,
        'opt': row.opt or 0.0, 'gd': row.gd or 0.0, 'holding': row.holding or 0.0,
        'shareholder': row.shareholder or 0.0, 'action': row.action or 0.0,
        'cadastre_date': row.cadastre_date.isoformat() if row.cadastre_date else None,
    }


def _price_options(sell, discounts, manual_percents, mortgage_settings):
    """Варианты оплаты для квартиры с учётом выбранных скидок."""
    discount_by_method = {
        method: _serialize_discount_row(data['row'])
        for method, data in discounts.items()
    }
    options = pricing_service.build_payment_options(sell.estate_price or 0, discount_by_method)

    for option in options:
        pricing_service.recalculate(option, manual_percents.get(option['type_key'], {}))

    pricing_service.apply_mortgage_terms(
        options,
        mortgage_settings.mortgage_rate_annual,
        mortgage_settings.mortgage_rate_after_cadastre,
        mortgage_settings.mortgage_term_months,
    )
    return {option['type_key']: option for option in options}


def build_offer(complex_name, filters=None, manual_percents=None, apply_all_discounts=True):
    """Лучшие лоты проекта под заданные критерии.

    Возвращает три показателя офера и по каждому — квартиру, из которой он
    взят: минимальная цена, минимальная цена за м² и минимальный ежемесячный
    платёж по ипотеке.
    """
    from .settings_service import get_calculator_settings

    filters = filters or {}
    manual_percents = manual_percents or {}
    mysql_session = get_mysql_session()

    query = mysql_session.query(EstateSell).join(
        EstateHouse, EstateSell.house_id == EstateHouse.id
    ).filter(
        EstateHouse.complex_name == complex_name,
        EstateSell.estate_sell_category == FLAT_CATEGORY,
        EstateSell.estate_sell_status_name.in_(AVAILABLE_STATUSES),
        EstateSell.estate_price.isnot(None),
    )

    # Фильтры «от» и «до» приходят из формы и могут быть пустыми.
    if filters.get('price_from'):
        query = query.filter(EstateSell.estate_price >= filters['price_from'])
    if filters.get('price_to'):
        query = query.filter(EstateSell.estate_price <= filters['price_to'])
    if filters.get('price_m2_from'):
        query = query.filter(EstateSell.estate_price_m2 >= filters['price_m2_from'])
    if filters.get('price_m2_to'):
        query = query.filter(EstateSell.estate_price_m2 <= filters['price_m2_to'])
    if filters.get('area_from'):
        query = query.filter(EstateSell.estate_area >= filters['area_from'])
    if filters.get('area_to'):
        query = query.filter(EstateSell.estate_area <= filters['area_to'])
    if filters.get('rooms'):
        query = query.filter(EstateSell.estate_rooms == filters['rooms'])

    flats = query.all()
    discounts = get_project_discounts(complex_name)
    settings = get_calculator_settings()

    # Скидки: либо всё доступное по матрице, либо выбранное менеджером.
    if apply_all_discounts:
        manual_percents = {
            pricing_service.FULL_PAYMENT_KEY: {
                item['code']: item['max_percent']
                for item in discounts.get(PaymentMethod.FULL_PAYMENT, {}).get('limits', [])
            },
            pricing_service.MORTGAGE_KEY: {
                item['code']: item['max_percent']
                for item in discounts.get(PaymentMethod.MORTGAGE, {}).get('limits', [])
            },
        }

    best = {'price': None, 'price_m2': None, 'monthly': None}
    considered = 0

    for sell in flats:
        options = _price_options(sell, discounts, manual_percents, settings)
        full = options.get(pricing_service.FULL_PAYMENT_KEY)
        mortgage = options.get(pricing_service.MORTGAGE_KEY)
        if not full:
            continue

        considered += 1
        final_price = full['final_price']
        price_m2 = final_price / sell.estate_area if sell.estate_area else None
        monthly = mortgage.get('monthly_payment') if mortgage else None

        # Фильтр по ипотеке задаётся как «от ХХ в месяц»: он отсекает слишком
        # дорогие платежи, а не дешёвые.
        if filters.get('monthly_to') and monthly and monthly > filters['monthly_to']:
            monthly = None

        candidate = {
            'sell_id': sell.id,
            'flat_number': sell.geo_flatnum,
            'floor': sell.estate_floor,
            'rooms': sell.estate_rooms,
            'area': sell.estate_area,
            'category': map_mysql_key_to_russian_value(sell.estate_sell_category),
            'base_price': sell.estate_price,
            'final_price': final_price,
            'price_m2': price_m2,
            'discount_percent': full['total_discount_percent'],
            'monthly_payment': monthly,
            'initial_payment': mortgage.get('initial_payment') if mortgage else None,
            'mortgage_term_months': mortgage.get('mortgage_term_months') if mortgage else None,
            'crm_url': flat_url(sell.id),
        }

        if best['price'] is None or final_price < best['price']['final_price']:
            best['price'] = candidate
        if price_m2 and (best['price_m2'] is None or price_m2 < best['price_m2']['price_m2']):
            best['price_m2'] = candidate
        if monthly and (best['monthly'] is None
                        or monthly < best['monthly']['monthly_payment']):
            best['monthly'] = candidate

    return {
        'complex_name': complex_name,
        'considered': considered,
        'best': best,
        'discounts': {
            'full_payment': discounts.get(PaymentMethod.FULL_PAYMENT, {}).get('limits', []),
            'mortgage': discounts.get(PaymentMethod.MORTGAGE, {}).get('limits', []),
        },
        'mortgage_configured': bool(settings.mortgage_term_months),
    }
