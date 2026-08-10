# app/services/complex_calc_service.py

from datetime import date
from dateutil.relativedelta import relativedelta
import numpy_financial as npf
from flask import current_app
from app.services import selection_service, settings_service, currency_service
from ..core.db_utils import get_planning_session
from app.models import planning_models
from app.models.planning_models import PaymentMethod

import math

DEFAULT_RATE = 16.5 / 12 / 100

# Константы для разных типов ипотеки
MAX_MORTGAGE_BODY_STANDARD = 420_000_000
MAX_MORTGAGE_BODY_EXTENDED = 840_000_000
MIN_DP_PERCENT_STANDARD = 0.15  # Процент
MIN_DP_PERCENT_EXTENDED = 0.25  # Процент


def calculate_installment_plan(sell_id: int, term_months: int, additional_discounts: dict, start_date=None,
                               dp_amount: float = 0, dp_type: str = 'uzs'):
    """
    Рассчитывает сложную рассрочку. Все скидки (МПП, РОП и т.д.) передаются пользователем.
    """
    settings = settings_service.get_calculator_settings()
    whitelist_str = settings.standard_installment_whitelist or ""
    whitelist = [int(x.strip()) for x in whitelist_str.split(',') if x.strip()]
    if sell_id not in whitelist:
        raise ValueError("Этот вид рассрочки недоступен для данного объекта.")

    monthly_rate = settings.time_value_rate_annual / 12 / 100

    card_data = selection_service.get_apartment_card_data(sell_id)
    apartment_price = card_data.get('apartment', {}).get('estate_price', 0)
    discounts_100_payment = next((d for d in card_data.get('all_discounts_for_property_type', []) if
                                  d['payment_method'] == PaymentMethod.FULL_PAYMENT.value), None)

    if not discounts_100_payment:
        raise ValueError("Скидки для 100% оплаты не найдены для этого объекта.")

    cadastre_date_str = discounts_100_payment.get('cadastre_date')
    if cadastre_date_str:
        cadastre_date = date.fromisoformat(cadastre_date_str)
        months_to_cadastre = relativedelta(cadastre_date, date.today()).months + relativedelta(cadastre_date,
                                                                                               date.today()).years * 12
        if term_months > months_to_cadastre:
            raise ValueError(f"Срок рассрочки не может превышать {months_to_cadastre} мес. (до кадастра)")
    elif term_months > 0:
        raise ValueError("Невозможно рассчитать рассрочку: не указана дата кадастра.")

    price_for_calc = apartment_price - 3_000_000
    if price_for_calc <= 0:
        raise ValueError("Базовая цена для расчета должна быть положительной.")

    dp_uzs = 0
    if dp_amount > 0:
        if dp_type == 'percent':
            dp_uzs = price_for_calc * (dp_amount / 100.0)
        elif dp_type == 'usd':
            usd_rate = currency_service.get_current_effective_rate()
            if not usd_rate: raise ValueError("Не удалось получить курс USD для расчета ПВ.")
            dp_uzs = dp_amount * usd_rate
        else:  # 'uzs'
            dp_uzs = dp_amount

    min_dp_percent = settings.standard_installment_min_dp_percent
    min_dp_uzs = price_for_calc * (min_dp_percent / 100.0)

    total_discount_rate = 0
    for disc_key, disc_value in additional_discounts.items():
        max_discount = discounts_100_payment.get(disc_key, 0)
        if disc_value > max_discount:
            raise ValueError(f"Скидка {disc_key.upper()} превышает максимум ({max_discount * 100}%)")
        total_discount_rate += disc_value

    if term_months <= 0:
        raise ValueError("Срок рассрочки должен быть больше нуля.")

    price_after_discounts_theoretical = price_for_calc * (1 - total_discount_rate)
    remaining_for_installment = price_after_discounts_theoretical - dp_uzs
    if remaining_for_installment <= 0:
        raise ValueError("Сумма первоначального взноса равна или превышает стоимость квартиры после скидок.")

    monthly_payment_theoretical = npf.pmt(monthly_rate, term_months, -remaining_for_installment)
    contract_value_theoretical = (monthly_payment_theoretical * term_months) + dp_uzs
    discount_percent_theoretical = (1 - (contract_value_theoretical / price_for_calc)) * 100

    final_discount_percent = math.floor(discount_percent_theoretical)
    final_discount_rate = final_discount_percent / 100.0
    final_contract_value = price_for_calc * (1 - final_discount_rate)
    final_installment_part = final_contract_value - dp_uzs
    final_monthly_payment = final_installment_part / term_months

    payment_schedule = []
    start_date_obj = date.fromisoformat(start_date) if start_date else date.today()

    payment_schedule.append({
        "month_number": 0,
        "payment_date": start_date_obj.isoformat(),
        "amount": dp_uzs,
        "type": "initial_payment"
    })

    current_payment_date = start_date_obj
    for i in range(1, term_months + 1):
        current_payment_date += relativedelta(months=1)
        payment_schedule.append({
            "month_number": i,
            "payment_date": current_payment_date.isoformat(),
            "amount": final_monthly_payment,
            "type": "monthly_payment"
        })

    return {
        "price_list": apartment_price,
        "initial_payment_uzs": dp_uzs,
        "calculated_discount": final_discount_percent,
        "calculated_contract_value": final_contract_value,
        "monthly_payment": final_monthly_payment,
        "term_months": term_months,
        "payment_schedule": payment_schedule
    }


def calculate_dp_installment_plan(sell_id: int, term_months: int, dp_amount: float, dp_type: str,
                                  additional_discounts: dict, start_date=None, mortgage_type: str = 'standard'):
    """
    Рассчитывает рассрочку на ПВ. Все скидки передаются пользователем.
    """
    settings = settings_service.get_calculator_settings()
    whitelist_str = settings.dp_installment_whitelist or ""
    whitelist = [int(x.strip()) for x in whitelist_str.split(',') if x.strip()]
    if sell_id not in whitelist:
        raise ValueError("Этот вид оплаты недоступен для данного объекта.")

    if not (1 <= term_months <= settings.dp_installment_max_term):
        raise ValueError(f"Срок рассрочки на ПВ должен быть от 1 до {settings.dp_installment_max_term} месяцев.")

    monthly_rate = settings.time_value_rate_annual / 12 / 100

    card_data = selection_service.get_apartment_card_data(sell_id)
    apartment_price = card_data.get('apartment', {}).get('estate_price', 0)
    discounts_mortgage = next((d for d in card_data.get('all_discounts_for_property_type', []) if
                               d['payment_method'] == PaymentMethod.MORTGAGE.value), None)

    if not discounts_mortgage:
        raise ValueError("Скидки для ипотеки не найдены для этого объекта.")

    price_for_calc = apartment_price - 3_000_000
    if price_for_calc <= 0:
        raise ValueError("Базовая цена для расчета должна быть положительной.")

    total_discount_rate = 0
    for disc_key, disc_value in additional_discounts.items():
        max_discount = discounts_mortgage.get(disc_key, 0)
        if disc_value > max_discount:
            raise ValueError(f"Скидка {disc_key.upper()} превышает максимум ({max_discount * 100}%)")
        total_discount_rate += disc_value

    price_after_discounts = price_for_calc * (1 - total_discount_rate)

    usd_rate = currency_service.get_current_effective_rate() or 13050

    if dp_type == 'percent':
        dp_uzs = price_after_discounts * (dp_amount / 100)
    elif dp_type == 'usd':
        dp_uzs = dp_amount * usd_rate
    else:
        dp_uzs = dp_amount

    if mortgage_type == 'extended':
        MAX_MORTGAGE_BODY = MAX_MORTGAGE_BODY_EXTENDED
        MIN_DP_PERCENT = MIN_DP_PERCENT_EXTENDED
    else:
        MAX_MORTGAGE_BODY = MAX_MORTGAGE_BODY_STANDARD
        MIN_DP_PERCENT = MIN_DP_PERCENT_STANDARD

    min_dp = price_after_discounts * MIN_DP_PERCENT
    if dp_uzs < min_dp:
        raise ValueError(f"Первоначальный взнос не может быть меньше {MIN_DP_PERCENT * 100}% ({min_dp:,.0f} UZS).")

    mortgage_body = price_after_discounts - dp_uzs
    if mortgage_body > MAX_MORTGAGE_BODY:
        increase_needed_uzs = mortgage_body - MAX_MORTGAGE_BODY
        if dp_type == 'percent':
            increase_needed_val = (increase_needed_uzs / price_after_discounts) * 100
            msg = f"Тело ипотеки превышает лимит. Увеличьте ПВ на {increase_needed_val:.2f}%."
        elif dp_type == 'usd':
            increase_needed_val = increase_needed_uzs / usd_rate
            msg = f"Тело ипотеки превышает лимит. Увеличьте ПВ на ${increase_needed_val:,.0f}."
        else:
            msg = f"Тело ипотеки превышает лимит. Увеличьте ПВ на {increase_needed_uzs:,.0f} UZS."
        raise ValueError(msg)

    monthly_payment_for_dp_theoretical = npf.pmt(monthly_rate, term_months, -dp_uzs)
    dp_value_theoretical = monthly_payment_for_dp_theoretical * term_months
    contract_value_theoretical = dp_value_theoretical + mortgage_body
    discount_percent_theoretical = (1 - (contract_value_theoretical / price_for_calc)) * 100

    final_discount_percent = math.floor(discount_percent_theoretical)
    final_discount_rate = final_discount_percent / 100.0

    final_contract_value = price_for_calc * (1 - final_discount_rate)
    final_dp_value = final_contract_value - mortgage_body
    final_monthly_payment_for_dp = final_dp_value / term_months if term_months > 0 else 0

    payment_schedule = []
    start_date_obj = date.fromisoformat(start_date) if start_date else date.today()
    current_payment_date = start_date_obj - relativedelta(months=1)

    for i in range(1, term_months + 1):
        current_payment_date += relativedelta(months=1)
        payment_schedule.append({
            "month_number": i,
            "payment_date": current_payment_date.isoformat(),
            "amount": final_monthly_payment_for_dp,
            "type": "dp_payment"
        })

    payment_schedule.append({
        "month_number": term_months + 1,
        "payment_date": (current_payment_date + relativedelta(months=1)).isoformat(),
        "amount": mortgage_body,
        "type": "mortgage_body"
    })

    return {
        "term_months": term_months,
        "monthly_payment_for_dp": final_monthly_payment_for_dp,
        "mortgage_body": mortgage_body,
        "calculated_contract_value": final_contract_value,
        "calculated_discount": final_discount_percent,
        "payment_schedule": payment_schedule
    }


def calculate_zero_mortgage(sell_id: int, term_months: int, dp_percent: int, additional_discounts: dict,
                            mortgage_type: str = 'standard'):
    """
    Рассчитывает ипотеку под ноль и формирует график платежей.
    """
    card_data = selection_service.get_apartment_card_data(sell_id)
    apartment_price = card_data.get('apartment', {}).get('estate_price', 0)

    discounts_100_payment = next((d for d in card_data.get('all_discounts_for_property_type', []) if
                                  d['payment_method'] == planning_models.PaymentMethod.FULL_PAYMENT.value), None)

    if not discounts_100_payment:
        raise ValueError("Скидки для 100% оплаты не найдены для этого объекта.")

    price_for_calc = apartment_price - 3_000_000
    if price_for_calc <= 0:
        raise ValueError("Базовая цена для расчета должна быть положительной.")

    total_discount_rate = 0
    for disc_key, disc_value in additional_discounts.items():
        max_discount = discounts_100_payment.get(disc_key, 0)
        if disc_value > max_discount:
            raise ValueError(f"Скидка {disc_key.upper()} превышает максимум ({max_discount * 100}%)")
        total_discount_rate += disc_value

    planning_session = get_planning_session()
    cashback_entry = planning_session.query(planning_models.ZeroMortgageMatrix).filter_by(term_months=term_months,
                                                                                          dp_percent=dp_percent).first()
    if not cashback_entry:
        raise ValueError(f"Не найдены условия для срока {term_months} мес. и ПВ {dp_percent}%")

    cashback_percent = cashback_entry.cashback_percent

    denominator = 1 - cashback_percent
    if denominator == 0:
        raise ValueError("Кэшбек не может быть равен 100%, это приведет к делению на ноль.")

    contract_value = (price_for_calc * (1 - total_discount_rate)) / denominator

    # --- ИЗМЕНЕНИЕ: Проверяем лимиты ипотеки ---
    if mortgage_type == 'extended':
        MAX_MORTGAGE_BODY = MAX_MORTGAGE_BODY_EXTENDED
        MIN_DP_PERCENT = MIN_DP_PERCENT_EXTENDED
    else:
        MAX_MORTGAGE_BODY = MAX_MORTGAGE_BODY_STANDARD
        MIN_DP_PERCENT = MIN_DP_PERCENT_STANDARD

    if dp_percent < MIN_DP_PERCENT:
        raise ValueError(f"Для этого типа ипотеки первоначальный взнос должен быть не менее {MIN_DP_PERCENT}%.")

    initial_payment = contract_value * (dp_percent / 100.0)
    remaining_amount = contract_value - initial_payment

    if remaining_amount > MAX_MORTGAGE_BODY:
        raise ValueError(
            f"Тело кредита ({remaining_amount:,.0f} UZS) превышает лимит в {MAX_MORTGAGE_BODY:,.0f} UZS для данного типа ипотеки.")
    # --- КОНЕЦ ИЗМЕНЕНИЯ ---

    monthly_payment = remaining_amount / term_months if term_months > 0 else 0

    payment_schedule = []
    start_date_obj = date.today()

    payment_schedule.append({
        "month_number": 0,
        "payment_date": start_date_obj.isoformat(),
        "amount": initial_payment,
        "type": "initial_payment"
    })

    current_payment_date = start_date_obj
    for i in range(1, term_months + 1):
        current_payment_date += relativedelta(months=1)
        payment_schedule.append({
            "month_number": i,
            "payment_date": current_payment_date.isoformat(),
            "amount": monthly_payment,
            "type": "monthly_payment"
        })

    return {
        "price_list": apartment_price,
        "contract_value": contract_value,
        "initial_payment": initial_payment,
        "monthly_payment": monthly_payment,
        "term_months": term_months,
        "dp_percent": dp_percent,
        "payment_schedule": payment_schedule
    }