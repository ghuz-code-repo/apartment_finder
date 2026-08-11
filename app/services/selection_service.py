# app/services/selection_service.py

from flask import current_app, abort
from sqlalchemy.orm import joinedload

from . import currency_service, pricing_service
from ..core.db_utils import get_mysql_session, get_planning_session, get_default_session
import json
from datetime import date

# --- ИЗМЕНЕНИЯ ЗДЕСЬ: Обновляем импорты ---
from ..models.estate_models import EstateHouse, EstateSell
from ..models import planning_models
from ..models.exclusion_models import ExcludedSell

# --- ДОБАВЛЯЕМ "ПЕРЕВОДЧИКИ" ---
from ..models.planning_models import map_russian_to_mysql_key, map_mysql_key_to_russian_value


VALID_STATUSES = ["Маркетинговый резерв", "Подбор"]

# Общие для карточки и поиска условия берём из pricing_service, чтобы цифры
# не разъезжались при правке в одном месте.
DEDUCTION_AMOUNT = pricing_service.DEDUCTION_AMOUNT
MAX_MORTGAGE_STANDARD = pricing_service.MAX_MORTGAGE_STANDARD
MIN_INITIAL_PAYMENT_PERCENT_STANDARD = pricing_service.MIN_INITIAL_PAYMENT_PERCENT_STANDARD

# Расширенная ипотека осталась только в подборе по бюджету: в карточке объекта
# и в КП показывается одна стандартная схема.
MAX_MORTGAGE_EXTENDED = 840_000_000
MIN_INITIAL_PAYMENT_PERCENT_EXTENDED = 0.25


def find_apartments_by_budget(budget: float, currency: str, property_type_str: str, floor: str = None,
                              rooms: str = None, payment_method: str = None):
    mysql_session = get_mysql_session()
    planning_session = get_planning_session()
    default_session = get_default_session()
    """
    Финальная версия с исправленной логикой области видимости переменной discount.
    """
    usd_rate = currency_service.get_current_effective_rate() or 12650.0
    budget_uzs = budget * usd_rate if currency.upper() == 'USD' else budget

    print(f"\n[SELECTION_SERVICE] 🔎 Поиск. Бюджет: {budget} {currency}. Тип: {property_type_str}")

    # Используем planning_models
    active_version = planning_session.query(planning_models.DiscountVersion).filter_by(is_active=True).first()
    if not active_version:
        print("[SELECTION_SERVICE] ❌ Не найдена активная версия скидок.")
        return {}

    property_type_enum = planning_models.PropertyType(property_type_str)

    # --- ИЗМЕНЕНИЕ: Получаем ключ MySQL ('flat') из русского property_type ('Квартира') ---
    mysql_category_key = map_russian_to_mysql_key(property_type_enum.value)
    # ---

    discounts_map = {
        (d.complex_name, d.payment_method): d
        for d in
        planning_session.query(planning_models.Discount).filter_by(version_id=active_version.id, property_type=property_type_enum).all()
    }
    excluded_sell_ids = {e.sell_id for e in default_session.query(ExcludedSell).all()}

    query = mysql_session.query(EstateSell).options(
        joinedload(EstateSell.house)
    ).filter(
        # --- ИЗМЕНЕНИЕ: Используем ключ MySQL ('flat') для фильтра ---
        EstateSell.estate_sell_category == mysql_category_key,
        EstateSell.estate_sell_status_name.in_(VALID_STATUSES),
        EstateSell.estate_price.isnot(None),
        EstateSell.estate_price > DEDUCTION_AMOUNT,
        EstateSell.id.notin_(excluded_sell_ids) if excluded_sell_ids else True
    )

    if floor and floor.isdigit():
        query = query.filter(EstateSell.estate_floor == int(floor))
    if rooms and rooms.isdigit():
        query = query.filter(EstateSell.estate_rooms == int(rooms))

    available_sells = query.all()
    print(f"[SELECTION_SERVICE] Найдено квартир до расчета: {len(available_sells)}")

    results = {}
    default_discount = planning_models.Discount()

    payment_methods_to_check = list(planning_models.PaymentMethod)
    if payment_method:
        selected_pm_enum = next((pm for pm in planning_models.PaymentMethod if pm.value == payment_method), None)
        if selected_pm_enum:
            payment_methods_to_check = [selected_pm_enum]

    for sell in available_sells:
        if not sell.house: continue

        complex_name = sell.house.complex_name
        base_price = sell.estate_price

        for payment_method_enum in payment_methods_to_check:
            is_match = False
            apartment_details = {}
            price_after_deduction = base_price - DEDUCTION_AMOUNT
            discount = discounts_map.get((complex_name, payment_method_enum), default_discount)

            if payment_method_enum == planning_models.PaymentMethod.FULL_PAYMENT:
                total_discount_rate = (discount.mpp or 0) + (discount.rop or 0) + (discount.action or 0)
                final_price_uzs = price_after_deduction * (1 - total_discount_rate)
                if budget_uzs >= final_price_uzs:
                    is_match = True
                    apartment_details = {"final_price": final_price_uzs}

            elif payment_method_enum == planning_models.PaymentMethod.MORTGAGE:
                total_discount_rate = (discount.mpp or 0) + (discount.rop or 0) + (discount.action or 0)
                price_after_discounts = price_after_deduction * (1 - total_discount_rate)
                # --- ИЗМЕНЕНИЕ: Проверяем оба типа ипотеки ---
                # Стандартная
                initial_payment_std = price_after_discounts - MAX_MORTGAGE_STANDARD
                min_required_std = price_after_discounts * MIN_INITIAL_PAYMENT_PERCENT_STANDARD
                if initial_payment_std >= min_required_std and budget_uzs >= initial_payment_std:
                    is_match = True
                    apartment_details = {"final_price": price_after_discounts, "initial_payment": initial_payment_std, "mortgage_type": "Стандартная"}

                # Расширенная
                initial_payment_ext = price_after_discounts - MAX_MORTGAGE_EXTENDED
                min_required_ext = price_after_discounts * MIN_INITIAL_PAYMENT_PERCENT_EXTENDED
                if initial_payment_ext >= min_required_ext and budget_uzs >= initial_payment_ext:
                    is_match = True
                    # Если подходит и стандартная, и расширенная, сохраняем оба варианта
                    if "mortgage_type" in apartment_details:
                         apartment_details["initial_payment_extended"] = initial_payment_ext
                    else:
                        apartment_details = {"final_price": price_after_discounts, "initial_payment": initial_payment_ext, "mortgage_type": "Расширенная"}

            if is_match:
                results.setdefault(complex_name, {"total_matches": 0, "by_payment_method": {}})
                payment_method_str = payment_method_enum.value
                results[complex_name]["by_payment_method"].setdefault(payment_method_str, {"total": 0, "by_rooms": {}})
                rooms_str = str(sell.estate_rooms) if sell.estate_rooms else "Студия"
                results[complex_name]["by_payment_method"][payment_method_str]["by_rooms"].setdefault(rooms_str, [])

                # --- ИСПРАВЛЕНИЕ ЗДЕСЬ ---
                details = {"id": sell.id, "floor": sell.estate_floor, "area": sell.estate_area,
                           "base_price": base_price, **apartment_details}
                # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

                results[complex_name]["by_payment_method"][payment_method_str]["by_rooms"][rooms_str].append(details)
                results[complex_name]["by_payment_method"][payment_method_str]["total"] += 1
                results[complex_name]["total_matches"] += 1

    print(f"[SELECTION_SERVICE] ✅ Поиск завершен.")
    return results


def get_apartment_card_data(sell_id: int):
    mysql_session = get_mysql_session()
    planning_session = get_planning_session()
    """
    Собирает все данные для детальной карточки квартиры.
    """
    sell = mysql_session.query(EstateSell).options(joinedload(EstateSell.house)).filter_by(id=sell_id).first()
    if not sell: abort(404)

    active_version = planning_session.query(planning_models.DiscountVersion).filter_by(is_active=True).first()
    if not active_version:
        return {'apartment': {}, 'pricing': [], 'all_discounts_for_property_type': []}

    # --- ИЗМЕНЕНИЕ: Конвертируем 'flat' -> 'Квартира' ---
    russian_category_value = map_mysql_key_to_russian_value(sell.estate_sell_category)
    try:
        # Используем русское значение для поиска в planning_models
        property_type_enum = planning_models.PropertyType(russian_category_value)
    except ValueError:
        return {'apartment': {}, 'pricing': [], 'all_discounts_for_property_type': []}
    # --- КОНЕЦ ИЗМЕНЕНИЯ ---

    all_discounts_for_property_type = planning_session.query(planning_models.Discount).filter_by(
        version_id=active_version.id,
        property_type=property_type_enum,
        complex_name=sell.house.complex_name
    ).all()

    serialized_discounts = [{
        'complex_name': d.complex_name, 'property_type': d.property_type.value,
        'payment_method': d.payment_method.value, 'mpp': d.mpp or 0.0, 'rop': d.rop or 0.0,
        'kd': d.kd or 0.0, 'opt': d.opt or 0.0, 'gd': d.gd or 0.0, 'holding': d.holding or 0.0,
        'shareholder': d.shareholder or 0.0, 'action': d.action or 0.0,
        'cadastre_date': d.cadastre_date.isoformat() if d.cadastre_date else None
    } for d in all_discounts_for_property_type]

    serialized_house = {
        'id': sell.house.id, 'complex_name': sell.house.complex_name, 'name': sell.house.name,
        'geo_house': sell.house.geo_house
    } if sell.house else {}

    serialized_apartment = {
        'id': sell.id, 'house_id': sell.house_id,
        # --- ИЗМЕНЕНИЕ: Показываем русское название ---
        'estate_sell_category': russian_category_value,
        'estate_floor': sell.estate_floor, 'estate_rooms': sell.estate_rooms, 'estate_price_m2': sell.estate_price_m2,
        'estate_sell_status_name': sell.estate_sell_status_name, 'estate_price': sell.estate_price,
        'estate_area': sell.estate_area, 'house': serialized_house
    }

    # Скидки уже отфильтрованы по ЖК запросом выше — хватает ключа по способу оплаты.
    discount_by_method = {
        planning_models.PaymentMethod(d['payment_method']): d
        for d in serialized_discounts
    }

    pricing_options = pricing_service.build_payment_options(
        serialized_apartment['estate_price'], discount_by_method
    )

    return {
        'apartment': serialized_apartment,
        'pricing': pricing_options,
        'all_discounts_for_property_type': serialized_discounts,
        'mortgage_terms': {
            'body': pricing_service.MAX_MORTGAGE_STANDARD,
            'min_initial_payment_percent': pricing_service.MIN_INITIAL_PAYMENT_PERCENT_STANDARD,
        },
    }