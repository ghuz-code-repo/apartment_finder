# app/services/pricing_service.py
"""Единая точка расчёта стоимости объекта: базовые скидки, ручные скидки менеджера,
100% оплата и стандартная ипотека.

Раньше формула жила в трёх местах — selection_service, main_routes и
apartment_card_java.js — и расходилась: карточка складывала проценты скидок,
а КП применял их каскадом, поэтому суммы на экране и в печати не совпадали.
Здесь используется аддитивная модель: все проценты складываются и применяются
к цене после вычета. Так же считает система скидок и рыночная аналитика.
"""

from datetime import date

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


def _clean_amount(value):
    """Сумма из формы или адреса КП. Мусор и отрицательные -> None."""
    if value is None or value == '':
        return None
    try:
        amount = float(str(value).replace(' ', '').replace('\u00a0', '').replace(',', '.'))
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


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
        # Дата кадастра из матрицы скидок: на ней меняется ставка по ипотеке.
        'cadastre_date': discount_row.get('cadastre_date'),
    }
    return recalculate(option, {})


def recalculate(option, manual_percents, initial_payment=None):
    """Пересчитывает вариант оплаты с учётом ручных скидок менеджера.

    manual_percents: {'kd': 3.0, ...} в процентах. Значение выше максимума из
    матрицы обрезается — менеджер не может выдать больше разрешённого, даже
    если подставит своё число в адрес КП.

    initial_payment: первый взнос по ипотеке, если менеджер задал его руками.
    Ниже минимума не опускаем по той же причине — цифру можно подставить в
    адрес КП в обход интерфейса.
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
        # Минимальный первый взнос — 15% от стоимости сделки, остальное берёт на
        # себя банк, но не больше MAX_MORTGAGE_STANDARD. Если 85% цены выходят
        # за лимит, разницу добирает первый взнос.
        min_initial_payment = max(price_after_discounts - MAX_MORTGAGE_STANDARD,
                                  price_after_discounts * MIN_INITIAL_PAYMENT_PERCENT_STANDARD)

        # Менеджер может увеличить взнос — тело кредита и платёж уменьшатся.
        # Меньше минимума банк не пропустит, больше стоимости сделки — бессмысленно.
        chosen = _clean_amount(initial_payment)
        if chosen is None or chosen < min_initial_payment:
            chosen = min_initial_payment
        chosen = min(chosen, price_after_discounts)

        option['min_initial_payment'] = min_initial_payment
        option['initial_payment'] = chosen
        option['mortgage_body'] = price_after_discounts - chosen
        # Сумма договора — это цена сделки: взнос и тело кредита её делят.
        option['final_price'] = price_after_discounts
    else:
        option['min_initial_payment'] = None
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


def _balance_after(principal, monthly_rate, payment, months):
    """Остаток долга через months платежей по аннуитету."""
    if months <= 0:
        return principal
    if monthly_rate <= 0:
        return max(principal - payment * months, 0.0)

    growth = (1 + monthly_rate) ** months
    return max(principal * growth - payment * (growth - 1) / monthly_rate, 0.0)


def months_until(target_date, today=None):
    """Сколько полных месяцев осталось до даты. Прошедшая дата -> 0."""
    if not target_date:
        return None
    if isinstance(target_date, str):
        try:
            target_date = date.fromisoformat(target_date)
        except ValueError:
            return None

    today = today or date.today()
    if target_date <= today:
        return 0

    months = (target_date.year - today.year) * 12 + (target_date.month - today.month)
    if target_date.day < today.day:
        months -= 1
    return max(months, 0)


def apply_mortgage_terms(options, rate_before_cadastre, rate_after_cadastre, term_months, today=None):
    """Дописывает в ипотечный вариант условия банка и ежемесячные платежи.

    До кадастра действует одна ставка, после — другая. На дату кадастра берётся
    фактический остаток долга и заново раскидывается по второй ставке на
    оставшийся срок, поэтому второй платёж обычно ниже первого.

    Вызывать после recalculate: платёж считается от тела кредита, а оно
    зависит от выставленных менеджером скидок.
    """
    term_months = int(term_months or 0)

    for option in options or []:
        if option.get('type_key') != MORTGAGE_KEY:
            continue

        body = option.get('mortgage_body')
        months_before = months_until(option.get('cadastre_date'), today)

        # Кадастр уже получен (или даты нет) — весь срок по одной ставке.
        # После кадастра логично считать по второй ставке, если она задана.
        if not months_before:
            single_rate = rate_after_cadastre if (months_before == 0 and rate_after_cadastre) else rate_before_cadastre
            option['mortgage_rate_annual'] = single_rate
            option['mortgage_rate_after_cadastre'] = None
            option['months_before_cadastre'] = None
            option['months_after_cadastre'] = None
            option['monthly_payment'] = monthly_annuity_payment(body, single_rate, term_months)
            option['monthly_payment_after_cadastre'] = None
            option['mortgage_term_months'] = term_months
            continue

        option['mortgage_rate_annual'] = rate_before_cadastre
        option['mortgage_term_months'] = term_months
        payment_before = monthly_annuity_payment(body, rate_before_cadastre, term_months)
        option['monthly_payment'] = payment_before

        # Кадастр позже конца кредита либо вторая ставка не задана — делить нечего.
        if not payment_before or months_before >= term_months or not rate_after_cadastre:
            option['mortgage_rate_after_cadastre'] = None
            option['months_before_cadastre'] = None
            option['months_after_cadastre'] = None
            option['monthly_payment_after_cadastre'] = None
            continue

        balance = _balance_after(float(body), float(rate_before_cadastre) / 100 / 12,
                                 payment_before, months_before)
        months_after = term_months - months_before

        option['mortgage_rate_after_cadastre'] = rate_after_cadastre
        option['months_before_cadastre'] = months_before
        option['months_after_cadastre'] = months_after
        option['monthly_payment_after_cadastre'] = monthly_annuity_payment(
            balance, rate_after_cadastre, months_after
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
