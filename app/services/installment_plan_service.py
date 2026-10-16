# app/services/installment_plan_service.py
"""Рассрочка по сетке «первоначальный взнос × срок».

Схема отличается от остальных расчётов тем, что рассрочка здесь стоит денег не
в виде процентов по кредиту, а в виде отказа от части скидки: у каждой пары
«ПВ + срок» своя цена в процентах, и она вычитается из доступных клиенту
скидок. Остаток после первого взноса делится на срок равными долями.

Сетка своя у каждого ЖК и хранится в InstallmentPlanRate. Пары, которой в
сетке нет, по проекту не существует — калькулятор её не предлагает.
"""
import logging

from sqlalchemy.exc import SQLAlchemyError

from ..core.db_utils import get_planning_session
from ..models import planning_models
from . import pricing_service, selection_service

logger = logging.getLogger(__name__)

# Надбавки за особые условия. В отличие от скидок матрицы, они не торгуются:
# менеджер их либо даёт целиком, либо нет.
OPT_PERCENT = 3
REFERRAL_PERCENT = 1

# ОПТ и реферальная включаются отдельными переключателями, поэтому в базовую
# скидку не входят, иначе ОПТ посчитался бы дважды.
BASE_DISCOUNT_EXCLUDED = ('opt', 'referral')


def get_grid_for_complex(complex_name):
    """Сетка, к которой привязан ЖК. Таблиц ещё нет — считаем, что сетки нет."""
    if not complex_name:
        return None
    session = get_planning_session()
    try:
        link = session.query(planning_models.InstallmentGridComplex).filter_by(
            complex_name=complex_name).first()
        return link.grid if link else None
    except SQLAlchemyError as exc:
        session.rollback()
        logger.warning('[INSTALLMENT] Сетка рассрочки недоступна: %s', exc)
        return None


def _matrix_rows(complex_name):
    grid = get_grid_for_complex(complex_name)
    return list(grid.rates) if grid else []


def get_matrix(complex_name):
    """Сетка ЖК: {(ПВ в процентах, срок в месяцах): доля стоимости рассрочки}."""
    return {(row.dp_percent, row.term_months): row.cost_rate or 0.0
            for row in _matrix_rows(complex_name)}


def get_matrix_options(complex_name):
    """Данные для формы: сроки, проценты ПВ и допустимые пары.

    Срок выбирается первым, поэтому для каждого срока отдаём свой список ПВ —
    иначе менеджер выбрал бы пару, которой в сетке нет.
    """
    matrix = get_matrix(complex_name)
    terms = sorted({term for _, term in matrix})
    dp_by_term = {
        term: sorted({dp for dp, t in matrix if t == term})
        for term in terms
    }
    return {
        'terms': terms,
        'dp_by_term': dp_by_term,
        'cost_percent': {f'{dp}:{term}': round(rate * 100, 2)
                         for (dp, term), rate in matrix.items()},
    }


def get_base_discount(card_data):
    """Базовая скидка объекта: всё, что даёт система скидок по 100% оплате.

    Берём готовые потолки из pricing_service, поэтому индивидуальная акция
    здесь уже заменила обычную, как и на карточке объекта.
    """
    option = next((o for o in card_data.get('pricing', [])
                   if o.get('type_key') == pricing_service.FULL_PAYMENT_KEY), None)
    if not option:
        return 0.0, []

    parts = [limit for limit in option.get('manual_discount_limits', [])
             if limit['code'] not in BASE_DISCOUNT_EXCLUDED]
    total = sum(limit['max_percent'] for limit in parts)
    return total, [{'name': p['name'], 'percent': p['max_percent']} for p in parts]


def calculate(sell_id, term_months, dp_percent, with_opt=False, with_referral=False):
    """Считает условия рассрочки для объекта.

    Бросает ValueError с понятным текстом, когда пара «ПВ + срок» недоступна
    или когда цена рассрочки съедает скидку целиком.
    """
    term_months = int(term_months)
    dp_percent = int(dp_percent)

    card_data = selection_service.get_apartment_card_data(sell_id)
    apartment = card_data.get('apartment') or {}
    if not apartment:
        raise ValueError('Объект не найден.')

    complex_name = (apartment.get('house') or {}).get('complex_name')
    matrix = get_matrix(complex_name)
    if not matrix:
        raise ValueError(f'Для ЖК «{complex_name}» сетка рассрочки не заполнена.')

    cost_rate = matrix.get((dp_percent, term_months))
    if cost_rate is None:
        raise ValueError(f'Рассрочка на {term_months} мес. при взносе {dp_percent}% '
                         f'по этому ЖК не предусмотрена.')

    base_percent, base_parts = get_base_discount(card_data)
    opt_percent = OPT_PERCENT if with_opt else 0
    referral_percent = REFERRAL_PERCENT if with_referral else 0
    cost_percent = round(cost_rate * 100, 2)

    # Округление вниз до сотых повторяет исходный расчёт: доступная скидка не
    # должна вырасти из-за погрешности сложения долей.
    available_percent = int((base_percent + opt_percent + referral_percent - cost_percent) * 100) / 100
    if available_percent < 0:
        raise ValueError(
            f'Скидок не хватает: рассрочка на {term_months} мес. стоит {cost_percent:g}%, '
            f'а доступно {base_percent + opt_percent + referral_percent:g}%.')

    base_price = apartment.get('estate_price') or 0
    price_after_deduction = base_price - pricing_service.DEDUCTION_AMOUNT
    if price_after_deduction <= 0:
        raise ValueError('Цена объекта меньше суммы бронирования.')

    deal_price = price_after_deduction * (1 - available_percent / 100)
    initial_payment = deal_price * dp_percent / 100
    remainder = deal_price - initial_payment
    area = apartment.get('estate_area') or 0

    return {
        'term_months': term_months,
        'dp_percent': dp_percent,
        'base_price': base_price,
        'deduction': pricing_service.DEDUCTION_AMOUNT,
        'price_after_deduction': price_after_deduction,
        'base_discount_percent': base_percent,
        'base_discount_parts': base_parts,
        'opt_percent': opt_percent,
        'referral_percent': referral_percent,
        'plan_cost_percent': cost_percent,
        'available_discount_percent': available_percent,
        'discount_amount': price_after_deduction - deal_price,
        'deal_price': deal_price,
        'price_per_sqm': deal_price / area if area else None,
        'initial_payment': initial_payment,
        'remainder': remainder,
        'monthly_payment': remainder / term_months if term_months else None,
    }


# --- Ведение сеток ----------------------------------------------------------

def list_grids():
    """Все сетки со связанными ЖК. Таблиц ещё нет — список пуст."""
    session = get_planning_session()
    try:
        return session.query(planning_models.InstallmentGrid).order_by(
            planning_models.InstallmentGrid.name).all()
    except SQLAlchemyError as exc:
        session.rollback()
        logger.warning('[INSTALLMENT] Список сеток недоступен: %s', exc)
        return []


def get_grid(grid_id):
    return get_planning_session().get(planning_models.InstallmentGrid, int(grid_id))


def grid_as_table(grid):
    """Сетка в виде, удобном шаблону: сроки, проценты ПВ и значения клеток."""
    rates = list(grid.rates) if grid else []
    terms = sorted({r.term_months for r in rates})
    dp_values = sorted({r.dp_percent for r in rates})
    cells = {f'{r.term_months}:{r.dp_percent}': round((r.cost_rate or 0) * 100, 2)
             for r in rates}
    return {'terms': terms, 'dp_values': dp_values, 'cells': cells}


def _parse_numbers(raw):
    """«12, 24,36» -> [12, 24, 36]. Повторы и мусор отбрасываются."""
    values = []
    for chunk in str(raw or '').replace(';', ',').split(','):
        chunk = chunk.replace('%', '').strip()
        if not chunk:
            continue
        try:
            value = int(float(chunk))
        except ValueError:
            continue
        if value > 0 and value not in values:
            values.append(value)
    return sorted(values)


def save_grid(grid_id, name, complex_names, terms_raw, dp_raw, cells):
    """Создаёт или обновляет сетку целиком.

    cells: {'срок:ПВ': строка с процентом}. Пустая клетка означает, что пара
    не продаётся, и строка для неё не создаётся.

    ЖК закреплён не более чем за одной сеткой, поэтому занятые чужой сеткой
    проекты отклоняем с понятным текстом, а не молча перевешиваем.
    """
    name = (name or '').strip()
    if not name:
        raise ValueError('Укажите название сетки.')

    terms = _parse_numbers(terms_raw)
    dp_values = _parse_numbers(dp_raw)
    if not terms or not dp_values:
        raise ValueError('Заполните сроки и проценты первоначального взноса.')

    session = get_planning_session()
    grid = get_grid(grid_id) if grid_id else None
    if grid is None:
        grid = planning_models.InstallmentGrid(name=name)
        session.add(grid)
        session.flush()
    else:
        grid.name = name

    selected = [c.strip() for c in (complex_names or []) if c and c.strip()]
    taken = session.query(planning_models.InstallmentGridComplex).filter(
        planning_models.InstallmentGridComplex.complex_name.in_(selected),
        planning_models.InstallmentGridComplex.grid_id != grid.id).all() if selected else []
    if taken:
        names = ', '.join(sorted(link.complex_name for link in taken))
        raise ValueError(f'Эти ЖК уже закреплены за другой сеткой: {names}.')

    session.query(planning_models.InstallmentGridComplex).filter_by(
        grid_id=grid.id).delete(synchronize_session=False)
    for complex_name in selected:
        session.add(planning_models.InstallmentGridComplex(
            grid_id=grid.id, complex_name=complex_name))

    session.query(planning_models.InstallmentGridRate).filter_by(
        grid_id=grid.id).delete(synchronize_session=False)
    filled = 0
    for term in terms:
        for dp_percent in dp_values:
            raw = (cells or {}).get(f'{term}:{dp_percent}')
            if raw is None or str(raw).strip() == '':
                continue
            try:
                percent = float(str(raw).replace(',', '.').strip())
            except ValueError:
                continue
            if percent <= 0:
                continue
            session.add(planning_models.InstallmentGridRate(
                grid_id=grid.id, term_months=term, dp_percent=dp_percent,
                cost_rate=percent / 100.0))
            filled += 1

    session.commit()
    return grid, filled


def delete_grid(grid_id):
    session = get_planning_session()
    grid = get_grid(grid_id)
    if grid:
        session.delete(grid)
        session.commit()
    return grid is not None
