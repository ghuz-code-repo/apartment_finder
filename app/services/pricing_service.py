# app/services/pricing_service.py
"""Единая точка расчёта стоимости объекта: базовые скидки, ручные скидки менеджера,
100% оплата и стандартная ипотека.

Раньше формула жила в трёх местах — selection_service, main_routes и
apartment_card_java.js — и расходилась: карточка складывала проценты скидок,
а КП применял их каскадом, поэтому суммы на экране и в печати не совпадали.
Здесь используется аддитивная модель: все проценты складываются и применяются
к цене после вычета. Так же считает система скидок и рыночная аналитика.
"""

from ..models.planning_models import PaymentMethod

# Бронирование: не участвует в скидках, вычитается из прайса до их применения.
DEDUCTION_AMOUNT = 3_000_000

# Стандартная ипотека — единственная схема, которую видит менеджер в карточке.
MAX_MORTGAGE_STANDARD = 420_000_000
MIN_INITIAL_PAYMENT_PERCENT_STANDARD = 0.15

# Все скидки менеджер выставляет вручную: матрица задаёт только потолок,
# ничего не применяется само. Порядок здесь определяет порядок полей в карточке.
MANUAL_DISCOUNT_FIELDS = (
    ('mpp', 'МПП'),
    ('rop', 'РОП'),
    ('kd', 'КД'),
    ('opt', 'ОПТ'),
    ('gd', 'ГД'),
    ('holding', 'Холдинг'),
    ('shareholder', 'Акционер'),
    ('action', 'Акция'),
)

FULL_PAYMENT_KEY = 'full_payment'
MORTGAGE_KEY = 'mortgage_standard'


def _as_percent(rate):
    """Доля из матрицы скидок (0.03) -> проценты (3.0)."""
    try:
        return round(float(rate or 0.0) * 100, 2)
    except (TypeError, ValueError):
        return 0.0


def _clean_percent(value):
    """Проценты, пришедшие от ползунка или из адреса КП. Мусор -> 0.

    Менеджер выставляет целые проценты, поэтому дробь округляется вниз:
    иначе подставленное в адрес 2.99 обошло бы шаг ползунка.
    """
    try:
        percent = float(value)
    except (TypeError, ValueError):
        return 0
    return max(0, int(percent))


def build_payment_options(base_price, discount_by_method):
    """Собирает варианты оплаты для карточки квартиры.

    discount_by_method: {PaymentMethod: сериализованная строка матрицы скидок}.
    Ипотека показывается, если по ЖК есть ипотечная строка матрицы: сама строка
    и означает, что схема для комплекса доступна. По размеру скидок в ней судить
    нельзя — теперь скидки нулевые до тех пор, пока менеджер их не выставит.
    """
    price_after_deduction = base_price - DEDUCTION_AMOUNT
    options = []

    full_payment_row = discount_by_method.get(PaymentMethod.FULL_PAYMENT)
    options.append(_new_option(FULL_PAYMENT_KEY, '100% оплата', base_price,
                               price_after_deduction, full_payment_row))

    mortgage_row = discount_by_method.get(PaymentMethod.MORTGAGE)
    if mortgage_row is not None:
        options.append(_new_option(MORTGAGE_KEY, 'Ипотека', base_price,
                                   price_after_deduction, mortgage_row))

    return options


def _new_option(type_key, title, base_price, price_after_deduction, discount_row):
    discount_row = discount_row or {}
    option = {
        'type_key': type_key,
        'payment_method': title,
        'base_price': base_price,
        'deduction': DEDUCTION_AMOUNT,
        'price_after_deduction': price_after_deduction,
        # Только те скидки, которые реально доступны по матрице: менеджеру
        # не показываем поля, в которые всё равно нечего ввести. Ползунок ходит
        # целыми процентами, поэтому дробный потолок округляем вниз.
        'manual_discount_limits': [
            {'code': code, 'name': name,
             'max_percent': int(_as_percent(discount_row.get(code)))}
            for code, name in MANUAL_DISCOUNT_FIELDS
            if int(_as_percent(discount_row.get(code))) > 0
        ],
        # Тело кредита зависит от цены после скидок и считается в recalculate.
        'mortgage_body': None,
    }
    return recalculate(option, {})


def recalculate(option, manual_percents):
    """Пересчитывает вариант оплаты с учётом ручных скидок менеджера.

    manual_percents: {'kd': 3.0, ...} в процентах. Значение выше максимума из
    матрицы обрезается — менеджер не может выдать больше разрешённого, даже
    если подставит своё число в адрес КП.
    """
    manual_percents = manual_percents or {}
    limits = {item['code']: item['max_percent'] for item in option.get('manual_discount_limits', [])}

    applied = []
    for code, name in MANUAL_DISCOUNT_FIELDS:
        percent = min(_clean_percent(manual_percents.get(code)), limits.get(code, 0.0))
        if percent > 0:
            applied.append({'code': code, 'name': name, 'percent': percent})

    price_after_deduction = option['price_after_deduction']
    total_percent = sum(d['percent'] for d in applied)

    for row in applied:
        row['amount'] = price_after_deduction * row['percent'] / 100

    discount_amount = price_after_deduction * total_percent / 100
    price_after_discounts = price_after_deduction - discount_amount

    option['applied_discounts'] = applied
    # Что дала скидка: и в процентах, и в деньгах — это то, что видит клиент в КП.
    option['total_discount_percent'] = round(total_percent, 2)
    option['total_discount_amount'] = discount_amount
    option['price_after_discounts'] = price_after_discounts

    if option['type_key'] == MORTGAGE_KEY:
        # Первый взнос — минимум 15% от стоимости сделки, остальное берёт на
        # себя банк, но не больше MAX_MORTGAGE_STANDARD. Если 85% цены выходят
        # за лимит, разницу добирает первый взнос.
        initial_payment = max(price_after_discounts - MAX_MORTGAGE_STANDARD,
                              price_after_discounts * MIN_INITIAL_PAYMENT_PERCENT_STANDARD)
        option['initial_payment'] = initial_payment
        option['mortgage_body'] = price_after_discounts - initial_payment
        # Сумма договора — это цена сделки: взнос и тело кредита её делят.
        option['final_price'] = price_after_discounts
    else:
        option['initial_payment'] = None
        option['mortgage_body'] = None
        option['final_price'] = price_after_discounts

    return option


def monthly_annuity_payment(principal, annual_rate_percent, term_months):
    """Ежемесячный аннуитетный платёж по телу кредита.

    Возвращает None, если условий недостаточно (нет тела кредита или не задан
    срок): в КП лучше не показать строку вообще, чем показать выдуманное число.
    """
    try:
        principal = float(principal or 0)
        term_months = int(term_months or 0)
        annual_rate_percent = float(annual_rate_percent or 0)
    except (TypeError, ValueError):
        return None

    if principal <= 0 or term_months <= 0:
        return None

    monthly_rate = annual_rate_percent / 100 / 12
    if monthly_rate <= 0:
        # Беспроцентная схема — тело делится на срок равными долями.
        return principal / term_months

    growth = (1 + monthly_rate) ** term_months
    return principal * monthly_rate * growth / (growth - 1)


def apply_mortgage_terms(options, annual_rate_percent, term_months):
    """Дописывает в ипотечный вариант условия банка и ежемесячный платёж.

    Вызывать после recalculate: платёж считается от тела кредита, а оно
    зависит от выставленных менеджером скидок.
    """
    for option in options or []:
        if option.get('type_key') != MORTGAGE_KEY:
            continue
        option['mortgage_rate_annual'] = annual_rate_percent
        option['mortgage_term_months'] = term_months
        option['monthly_payment'] = monthly_annuity_payment(
            option.get('mortgage_body'), annual_rate_percent, term_months
        )
    return options


def parse_manual_selections(raw_json):
    """Разбирает ?selections={"full_payment": {"kd": 3}} из адреса КП."""
    import json

    if not raw_json:
        return {}
    try:
        parsed = json.loads(raw_json)
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}

    return {
        str(type_key): {str(code): _clean_percent(value) for code, value in discounts.items()}
        for type_key, discounts in parsed.items()
        if isinstance(discounts, dict)
    }
