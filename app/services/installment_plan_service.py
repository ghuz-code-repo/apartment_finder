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


def _matrix_rows(complex_name):
    """Строки сетки по ЖК. Таблицы ещё нет — считаем, что сетка пуста."""
    if not complex_name:
        return []
    session = get_planning_session()
    try:
        return session.query(planning_models.InstallmentPlanRate).filter_by(
            complex_name=complex_name).all()
    except SQLAlchemyError as exc:
        session.rollback()
        logger.warning('[INSTALLMENT] Сетка рассрочки недоступна: %s', exc)
        return []


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

# --- Загрузка и выгрузка сетки ----------------------------------------------

# Формат файла: строка на пару «ЖК + срок», колонки с процентами ПВ.
# Пустая клетка означает, что такой пары по проекту нет.
GRID_COMPLEX_COLUMNS = ('ЖК', 'Название ЖК', 'Комплекс')
GRID_TERM_COLUMNS = ('Срок, мес', 'Срок', 'Месяц', 'Срок рассрочки')


def _pick_column(columns, candidates):
    for name in candidates:
        if name in columns:
            return name
    return None


def _as_rate(value):
    """Цена рассрочки из файла в долю: 9 -> 0.09, 0.09 -> 0.09.

    Файл выгружается в процентах, но сетку нередко заполняют долями, поэтому
    значения не больше единицы считаем уже долями.
    """
    rate = float(value)
    return rate if rate <= 1 else rate / 100.0


def import_grid_from_excel(file_storage):
    """Заменяет сетку рассрочки для ЖК, перечисленных в файле.

    Трогаем только те проекты, что есть в файле: сетки остальных остаются.
    Возвращает текст для flash-сообщения.
    """
    import pandas as pd

    df = pd.read_excel(file_storage)
    complex_column = _pick_column(df.columns, GRID_COMPLEX_COLUMNS)
    term_column = _pick_column(df.columns, GRID_TERM_COLUMNS)
    if complex_column is None or term_column is None:
        raise ValueError(f'Нужны колонки «{GRID_COMPLEX_COLUMNS[0]}» и «{GRID_TERM_COLUMNS[0]}».')

    dp_columns = {}
    for column in df.columns:
        if column in (complex_column, term_column):
            continue
        try:
            # Заголовок колонки — процент ПВ: 20, «20», «20%».
            dp_columns[column] = int(float(str(column).replace('%', '').strip()))
        except ValueError:
            continue
    if not dp_columns:
        raise ValueError('Не найдено ни одной колонки с процентом первоначального взноса.')

    session = get_planning_session()
    touched, added = set(), 0

    for _, row in df.iterrows():
        complex_name = str(row[complex_column]).strip()
        if not complex_name or complex_name.lower() == 'nan':
            continue
        try:
            term_months = int(row[term_column])
        except (TypeError, ValueError):
            continue

        if complex_name not in touched:
            session.query(planning_models.InstallmentPlanRate).filter_by(
                complex_name=complex_name).delete(synchronize_session=False)
            touched.add(complex_name)

        for column, dp_percent in dp_columns.items():
            value = row[column]
            if pd.isna(value):
                continue
            try:
                rate = _as_rate(value)
            except (TypeError, ValueError):
                continue
            session.add(planning_models.InstallmentPlanRate(
                complex_name=complex_name, term_months=term_months,
                dp_percent=dp_percent, cost_rate=rate))
            added += 1

    session.commit()
    return f'Сетка рассрочки обновлена: проектов {len(touched)}, комбинаций {added}.'


def export_grid_to_excel():
    """Текущая сетка в том же виде, в каком её принимает загрузка."""
    import io as _io

    import pandas as pd

    session = get_planning_session()
    rows = session.query(planning_models.InstallmentPlanRate).order_by(
        planning_models.InstallmentPlanRate.complex_name,
        planning_models.InstallmentPlanRate.term_months).all()

    dp_values = sorted({row.dp_percent for row in rows})
    table = {}
    for row in rows:
        key = (row.complex_name, row.term_months)
        table.setdefault(key, {})[row.dp_percent] = round((row.cost_rate or 0) * 100, 2)

    data = []
    for (complex_name, term_months), by_dp in table.items():
        record = {GRID_COMPLEX_COLUMNS[0]: complex_name, GRID_TERM_COLUMNS[0]: term_months}
        record.update({dp: by_dp.get(dp) for dp in dp_values})
        data.append(record)

    columns = [GRID_COMPLEX_COLUMNS[0], GRID_TERM_COLUMNS[0]] + dp_values
    output = _io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        pd.DataFrame(data, columns=columns).to_excel(writer, index=False,
                                                     sheet_name='Сетка рассрочки')
    output.seek(0)
    return output
