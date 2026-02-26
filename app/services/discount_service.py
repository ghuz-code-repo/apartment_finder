# app/services/discount_service.py

import json
import copy
from datetime import date, datetime
from sqlalchemy.orm import joinedload
from flask import render_template_string
import requests
import pandas as pd
import io
from . import currency_service
from ..core.db_utils import get_planning_session, get_mysql_session, get_default_session
# --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
# Импортируем модуль planning_models
from ..models import planning_models
from ..models.estate_models import EstateSell
from .email_service import send_email
from ..models.planning_models import map_russian_to_mysql_key

def delete_draft_version(version_id: int):
    """Удаляет версию, если она никогда не была активна."""
    # Обращаемся к модели через planning_models
    planning_session = get_planning_session()  # <--- ДОБАВЛЕНО
    version_to_delete = planning_session.query(planning_models.DiscountVersion).get(version_id)  # <--- ИЗМЕНЕНО
    if not version_to_delete:
        raise ValueError("Версия для удаления не найдена.")

    if version_to_delete.was_ever_activated:
        raise PermissionError("Нельзя удалить версию, которая уже была активирована.")

    print(f"[DISCOUNT SERVICE] 🗑️ Удаление черновика версии №{version_to_delete.version_number} (ID: {version_id})")
    planning_session.delete(version_to_delete)  # <--- ИЗМЕНО
    planning_session.commit()
    print(f"[DISCOUNT SERVICE] ✔️ Черновик успешно удален.")



def _normalize_percentage(value):
    try:
        num_value = float(value)
        if num_value > 1.0: return num_value / 100.0 # Исправлено на правильное деление
        return num_value
    except (ValueError, TypeError):
        return 0.0

def process_discounts_from_excel(file_path: str, version_id: int):
    """
    Обрабатывает Excel-файл и создает/обновляет скидки для УКАЗАННОЙ ВЕРСИИ.
    """
    print(f"\n[DISCOUNT SERVICE] Начало обработки файла: {file_path} для версии ID: {version_id}")
    df = pd.read_excel(file_path)
    print("[DISCOUNT SERVICE] Загруженный DataFrame:\n", df.head())
    if df.empty:
        return "Ошибка: Файл Excel пуст или не содержит данных."

    created_count, updated_count = 0, 0
    planning_session = get_planning_session()
    existing_discounts = {
        (d.complex_name, d.property_type, d.payment_method): d
        for d in planning_session.query(planning_models.Discount).filter_by(version_id=version_id).all()
        # <--- ИЗМЕНЕНО
    }

    for index, row in df.iterrows():
        try:
            prop_type_val = row['Тип недвижимости']
            payment_method_val = row['Тип оплаты']

            # Используем Enum из planning_models
            property_type_enum = planning_models.PropertyType(prop_type_val)
            payment_method_enum = planning_models.PaymentMethod(payment_method_val)

            key = (row['ЖК'], property_type_enum, payment_method_enum)
            discount = existing_discounts.get(key)

            if not discount:
                # Создаем объект из planning_models
                discount = planning_models.Discount(
                    version_id=version_id,
                    complex_name=row['ЖК'],
                    property_type=property_type_enum,
                    payment_method=payment_method_enum
                )
                planning_session.add(discount)
                created_count += 1
            else:
                updated_count += 1

            discount.mpp = _normalize_percentage(row.get('МПП'))
            discount.rop = _normalize_percentage(row.get('РОП'))
            discount.kd = _normalize_percentage(row.get('КД'))
            discount.opt = _normalize_percentage(row.get('ОПТ'))
            discount.gd = _normalize_percentage(row.get('ГД'))
            discount.holding = _normalize_percentage(row.get('Холдинг'))
            discount.shareholder = _normalize_percentage(row.get('Акционер'))
            discount.action = _normalize_percentage(row.get('Акция'))

            cadastre_date_val = row.get('Дата кадастра')
            if pd.notna(cadastre_date_val):
                discount.cadastre_date = pd.to_datetime(cadastre_date_val).date()
            else:
                discount.cadastre_date = None
        except Exception as ex:
            print(f"[DISCOUNT SERVICE] ❌ ОШИБКА ОБРАБОТКИ СТРОКИ {index}: {ex}. Пропускаю.")

    print(f"[DISCOUNT SERVICE] Завершение. Создано: {created_count}, Обновлено: {updated_count}.")
    return f"Обработано {len(df)} строк. Создано: {created_count}, Обновлено: {updated_count}."


def generate_discount_template_excel():
    from .data_service import get_all_complex_names
    print("[DISCOUNT SERVICE] Генерация заполненного шаблона скидок...")

    planning_session = get_planning_session()
    complex_names = get_all_complex_names()

    # 1. Получаем активную версию и её скидки для предзаполнения
    active_version = planning_session.query(planning_models.DiscountVersion).filter_by(is_active=True).first()
    existing_discounts = {}

    if active_version:
        # Создаем карту: (ЖК, Тип недвижимости, Тип оплаты) -> объект скидки
        existing_discounts = {
            (d.complex_name, d.property_type, d.payment_method): d
            for d in active_version.discounts
        }
        print(f"[DISCOUNT SERVICE] Найдена активная версия №{active_version.version_number}, подгружаем данные.")

    headers = ['ЖК', 'Тип недвижимости', 'Тип оплаты', 'Дата кадастра', 'МПП', 'РОП', 'КД', 'ОПТ', 'ГД', 'Холдинг',
               'Акционер', 'Акция']
    data = []

    percentage_fields = ['mpp', 'rop', 'kd', 'opt', 'gd', 'holding', 'shareholder', 'action']

    for name in complex_names:
        for prop_type in planning_models.PropertyType:
            for payment_method in planning_models.PaymentMethod:
                # Ищем существующую скидку в базе
                discount_obj = existing_discounts.get((name, prop_type, payment_method))

                # Базовая структура строки
                row = {
                    'ЖК': name,
                    'Тип недвижимости': prop_type.value,
                    'Тип оплаты': payment_method.value,
                    'Дата кадастра': ''
                }

                # Если скидка есть, заполняем данными (переводим из долей в целые проценты для удобства редактирования)
                if discount_obj:
                    row['Дата кадастра'] = discount_obj.cadastre_date if discount_obj.cadastre_date else ''
                    for field in percentage_fields:
                        val = getattr(discount_obj, field) or 0.0
                        # Записываем как целое число (0.05 -> 5.0),
                        # так как _normalize_percentage при загрузке корректно обработает значения > 1
                        header_name = field.upper() if field != 'action' else 'Акция'
                        if field == 'shareholder': header_name = 'Акционер'  # Соответствие заголовкам

                        # Сопоставляем технические имена полей с заголовками Excel
                        header_map = {
                            'mpp': 'МПП', 'rop': 'РОП', 'kd': 'КД', 'opt': 'ОПТ',
                            'gd': 'ГД', 'holding': 'Холдинг', 'shareholder': 'Акционер', 'action': 'Акция'
                        }
                        row[header_map[field]] = val * 100.0
                else:
                    # Если данных нет, заполняем нулями
                    for field in percentage_fields:
                        header_map = {
                            'mpp': 'МПП', 'rop': 'РОП', 'kd': 'КД', 'opt': 'ОПТ',
                            'gd': 'ГД', 'holding': 'Холдинг', 'shareholder': 'Акционер', 'action': 'Акция'
                        }
                        row[header_map[field]] = 0

                data.append(row)

    # 2. Формируем Excel
    df = pd.DataFrame(data, columns=headers)
    output = io.BytesIO()

    # Используем xlsxwriter для настройки форматирования (опционально)
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Текущие скидки')

    output.seek(0)
    print(f"[DISCOUNT SERVICE] Шаблон успешно сформирован. Строк: {len(data)}")
    return output


# app/services/discount_service.py

# app/services/discount_service.py

# app/services/discount_service.py

def get_discounts_with_summary():
    """
    Получает данные для страницы "Система скидок", включая комментарии к ЖК.
    """
    planning_session = get_planning_session()
    mysql_session = get_mysql_session()

    print("\n" + "=" * 80)
    print("[DISCOUNT SERVICE DEBUG] 🔍 НАЧАЛО get_discounts_with_summary()")
    print("=" * 80)
    mysql_flat_key = map_russian_to_mysql_key(planning_models.PropertyType.FLAT.value)  # <-- ИСПОЛЬЗУЕМ МАППЕР
    print(f"[5.5] MySQL ключ для 'Квартира': {mysql_flat_key}")
    try:
        # 1. Проверяем активную версию скидок
        active_version = planning_session.query(planning_models.DiscountVersion).filter_by(is_active=True).first()
        print(f"[1] Активная версия скидок: {active_version.version_number if active_version else 'НЕ НАЙДЕНА'}")

        if not active_version:
            print("[DISCOUNT SERVICE DEBUG] ❌ Нет активной версии скидок!")
            return {}

        usd_rate = currency_service.get_current_effective_rate()
        if not usd_rate or usd_rate <= 0:
            print("[DISCOUNT SERVICE] ❕ Не удалось получить 'effective_rate', использую fallback: 13000.0")
            usd_rate = 13000.0
        print(f"[2] Курс USD: {usd_rate}")

        all_discounts = active_version.discounts
        print(f"[3] Всего скидок в версии: {len(all_discounts)}")

        comments = planning_session.query(planning_models.ComplexComment).filter_by(version_id=active_version.id).all()
        comments_map = {c.complex_name: c.comment for c in comments}
        print(f"[4] Комментариев к ЖК: {len(comments_map)}")

        if not all_discounts:
            print("[DISCOUNT SERVICE DEBUG] ❌ В активной версии нет скидок!")
            return {}

        discounts_map = {}
        for d in all_discounts:
            discounts_map.setdefault(d.complex_name, []).append(d)

        print(f"[5] Уникальных ЖК в скидках: {len(discounts_map)}")
        print(f"    Список ЖК: {list(discounts_map.keys())[:5]}...")  # Первые 5

        # --- КРИТИЧЕСКИЙ ЗАПРОС: Получаем квартиры из MySQL ---
        print("\n[6] 🔍 ЗАПРОС К MYSQL: Получаем все квартиры...")
        all_sells = mysql_session.query(EstateSell).options(joinedload(EstateSell.house)).all()
        print(f"[6] ✅ Получено квартир из MySQL: {len(all_sells)}")

        # Проверяем первые несколько квартир
        if all_sells:
            print("\n[7] 🔍 ПРИМЕР ДАННЫХ (первые 3 квартиры):")
            for i, sell in enumerate(all_sells[:3]):
                print(f"    [{i + 1}] ID: {sell.id}")
                print(f"        - ЖК: {sell.house.complex_name if sell.house else 'НЕТ ДОМА'}")
                print(f"        - Статус: '{sell.estate_sell_status_name}'")
                print(f"        - Категория: '{sell.estate_sell_category}'")
                print(f"        - Цена: {sell.estate_price}")
                print(f"        - Площадь: {sell.estate_area}")
        else:
            print("[7] ❌ НЕТ КВАРТИР В БАЗЕ ДАННЫХ!")

        # Группируем по ЖК
        sells_by_complex = {}
        for s in all_sells:
            if s.house:
                sells_by_complex.setdefault(s.house.complex_name, []).append(s)

        print(f"\n[8] Квартир сгруппировано по ЖК: {len(sells_by_complex)}")
        print(f"    Список ЖК с квартирами: {list(sells_by_complex.keys())[:5]}...")

        final_data = {}
        valid_statuses = ["Маркетинговый резерв", "Подбор"]
        print(f"\n[9] Валидные статусы для подсчета: {valid_statuses}")

        tag_fields = {'kd': 'КД', 'opt': 'ОПТ', 'gd': 'ГД', 'holding': 'Холдинг', 'shareholder': 'Акционер'}
        all_complex_names = sorted(list(discounts_map.keys()))

        print(f"\n[10] 🔄 НАЧИНАЕМ ОБРАБОТКУ {len(all_complex_names)} ЖК...")

        for idx, complex_name in enumerate(all_complex_names):
            print(f"\n    --- ЖК #{idx + 1}: '{complex_name}' ---")

            summary = {
                "sum_100_payment": 0, "sum_mortgage": 0, "months_to_cadastre": None,
                "avg_remainder_price_sqm": 0, "available_tags": set(), "max_action_discount": 0.0
            }
            summary["complex_comment"] = comments_map.get(complex_name)
            discounts_in_complex = discounts_map.get(complex_name, [])
            details_by_prop_type = {pt.value: [] for pt in planning_models.PropertyType}

            for d in discounts_in_complex:
                details_by_prop_type[d.property_type.value].append(d)

            base_discount_100 = next((d for d in discounts_in_complex
                                      if d.property_type == planning_models.PropertyType.FLAT
                                      and d.payment_method == planning_models.PaymentMethod.FULL_PAYMENT), None)
            if base_discount_100:
                summary["sum_100_payment"] = (base_discount_100.mpp or 0) + (base_discount_100.rop or 0)
                if base_discount_100.cadastre_date and base_discount_100.cadastre_date > date.today():
                    delta = base_discount_100.cadastre_date - date.today()
                    summary["months_to_cadastre"] = int(delta.days / 30.44)

            base_discount_mortgage = next((d for d in discounts_in_complex
                                           if d.property_type == planning_models.PropertyType.FLAT
                                           and d.payment_method == planning_models.PaymentMethod.MORTGAGE), None)
            if base_discount_mortgage:
                summary["sum_mortgage"] = (base_discount_mortgage.mpp or 0) + (base_discount_mortgage.rop or 0)

            total_discount_rate = sum(getattr(base_discount_100, f, 0) or 0
                                      for f in ['mpp', 'rop', 'kd', 'action']) if base_discount_100 else 0

            # --- КРИТИЧЕСКАЯ ПРОВЕРКА: Подсчет остатков ---
            sells_in_this_complex = sells_by_complex.get(complex_name, [])
            print(f"        Всего квартир в ЖК: {len(sells_in_this_complex)}")

            # Фильтруем по статусам
            valid_status_count = 0
            flat_category_count = 0
            price_and_area_ok_count = 0

            remainder_prices_per_sqm = []

            for sell in sells_in_this_complex:
                # Проверка 1: Статус
                if sell.estate_sell_status_name in valid_statuses:
                    valid_status_count += 1

                    # Проверка 2: Категория (Квартира)
                    if sell.estate_sell_category == mysql_flat_key:
                        flat_category_count += 1

                        # Проверка 3: Цена и площадь
                        if sell.estate_price and sell.estate_area:
                            price_and_area_ok_count += 1

                            price_after_deduction = sell.estate_price - 3_000_000
                            if price_after_deduction > 0:
                                final_price = price_after_deduction * (1 - total_discount_rate)
                                remainder_prices_per_sqm.append(final_price / sell.estate_area)

            print(f"        ├─ С валидным статусом: {valid_status_count}")
            print(f"        ├─ Из них категория 'Квартира': {flat_category_count}")
            print(f"        ├─ С ценой и площадью: {price_and_area_ok_count}")
            print(f"        └─ Прошли все проверки: {len(remainder_prices_per_sqm)}")

            if remainder_prices_per_sqm:
                avg_price_per_sqm_usd = (sum(remainder_prices_per_sqm) / len(remainder_prices_per_sqm)) / usd_rate
                summary["avg_remainder_price_sqm"] = avg_price_per_sqm_usd
                print(f"        ✅ Средняя цена остатков: ${avg_price_per_sqm_usd:.2f}/м²")
            else:
                print(f"        ❌ НЕТ ОСТАТКОВ для расчета!")

            for discount in discounts_in_complex:
                if discount.action is not None and discount.action > summary["max_action_discount"]:
                    summary["max_action_discount"] = discount.action

                for field, tag_name in tag_fields.items():
                    value = getattr(discount, field)
                    if value is not None and value > 0:
                        summary["available_tags"].add(tag_name)

            final_data[complex_name] = {"summary": summary, "details": details_by_prop_type}

        print("\n" + "=" * 80)
        print(f"[ИТОГ] Обработано ЖК: {len(final_data)}")
        print("=" * 80 + "\n")

        return final_data

    finally:
        planning_session.close()
        mysql_session.close()


def _generate_version_comparison_summary(old_version, new_version, comments_data=None):
    if comments_data is None: comments_data = {}
    old_discounts = {(d.complex_name, d.property_type.value, d.payment_method.value): d for d in old_version.discounts}
    new_discounts = {(d.complex_name, d.property_type.value, d.payment_method.value): d for d in new_version.discounts}
    changes = {'added': [], 'removed': [], 'modified': [], 'user_comments': comments_data}

    for key, new_d in new_discounts.items():
        if key not in old_discounts:
            changes['added'].append(f"Добавлена скидка для {key[0]} ({key[1]}, {key[2]})")
            continue
        old_d, diffs = old_discounts[key], []
        for field in ['mpp', 'rop', 'kd', 'opt', 'gd', 'holding', 'shareholder', 'action']:
            old_val, new_val = getattr(old_d, field) or 0.0, getattr(new_d, field) or 0.0
            if abs(old_val - new_val) > 1e-9:
                delta, verb = new_val - old_val, "увеличилась на" if new_val > old_val else "уменьшилась на"
                diffs.append(f"<b>{field.upper()}</b> {verb} {abs(delta * 100):.1f}% (с {old_val * 100:.1f}% до {new_val * 100:.1f}%)")
        if diffs:
            changes['modified'].append(f"<strong>{key[0]} ({key[1]}, {key[2]}):</strong><ul>{''.join(f'<li>{d}</li>' for d in diffs)}</ul>")

    for key in old_discounts:
        if key not in new_discounts:
            changes['removed'].append(f"Удалена скидка для {key[0]} ({key[1]}, {key[2]})")

    return render_template_string("""...""", old_v=old_version, new_v=new_version, changes=changes) # HTML template left as is for brevity


def create_blank_version(comment: str):
    """Создает новую, ПУСТУЮ запись о версии скидок БЕЗ КОММИТА."""
    planning_session = get_planning_session()  # <--- ДОБАВЛЕНО
    latest_version = planning_session.query(planning_models.DiscountVersion).order_by(
        planning_models.DiscountVersion.version_number.desc()).first()
    new_version_number = (latest_version.version_number + 1) if latest_version else 1
    new_version = planning_models.DiscountVersion(version_number=new_version_number, comment=comment)
    planning_session.add(new_version)  # <--- ИЗМЕНЕНО
    planning_session.flush()
    print(f"[DISCOUNT SERVICE] ✔️ Подготовлена пустая версия №{new_version_number}")
    return new_version


def clone_version_for_editing(active_version):
    """
    Создает полную копию активной версии в виде нового неактивного черновика.
    """
    if not active_version: raise ValueError("Нет активной версии для клонирования.")
    planning_session = get_planning_session()  # <--- ДОБАВЛЕНО
    latest_version = planning_session.query(planning_models.DiscountVersion).order_by(
        planning_models.DiscountVersion.version_number.desc()).first()  # <--- ИЗМЕНЕНО
    new_version_number = latest_version.version_number + 1
    draft_version = planning_models.DiscountVersion(version_number=new_version_number, comment=f"Черновик на основе v.{active_version.version_number}", is_active=False)
    planning_session.add(draft_version)  # <--- ИЗМЕНЕНО
    planning_session.flush()

    for old_discount in active_version.discounts:
        new_discount = planning_models.Discount(version_id=draft_version.id, **{k: getattr(old_discount, k) for k in ['complex_name', 'property_type', 'payment_method', 'mpp', 'rop', 'kd', 'opt', 'gd', 'holding', 'shareholder', 'action', 'cadastre_date']})
        planning_session.add(new_discount)
    for old_comment in active_version.complex_comments:
        new_comment = planning_models.ComplexComment(version_id=draft_version.id, complex_name=old_comment.complex_name, comment=old_comment.comment)
        planning_session.add(new_comment)

    planning_session.commit()
    print(f"[DISCOUNT SERVICE] ✔️ Создан черновик версии №{draft_version.version_number}")
    return draft_version


def update_discounts_for_version(version_id: int, form_data: dict, changes_json: str):
    """
    Обновляет скидки для УКАЗАННОЙ ВЕРСИИ (черновика) и ПЕРЕЗАПИСЫВАЕТ JSON-саммари.
    """
    planning_session = get_planning_session()  # <--- ДОБАВЛЕНО
    target_version = planning_session.query(planning_models.DiscountVersion).get(version_id)
    if not target_version or target_version.is_active: return "Ошибка: Версия не найдена или активна."

    discounts_map = {(d.complex_name, d.property_type.value, d.payment_method.value): d for d in target_version.discounts}
    updated_fields_count = 0

    for key, field_value in form_data.items():
        if key.startswith('discount-'):
            try:
                _, business_key_str, field_name = key.split('-', 2)
                complex_name, prop_type, payment_method = business_key_str.split('|')
                discount_to_update = discounts_map.get((complex_name, prop_type, payment_method))
                if discount_to_update:
                    new_value = float(field_value) / 100.0
                    if abs(getattr(discount_to_update, field_name, 0.0) - new_value) > 1e-9:
                        setattr(discount_to_update, field_name, new_value)
                        updated_fields_count += 1
            except (ValueError, TypeError): continue

    target_version.changes_summary_json = changes_json
    if updated_fields_count > 0:
        planning_session.commit()
        return "Изменения успешно сохранены."
    planning_session.rollback() # No need to commit if only JSON changed
    return "Изменений для сохранения не найдено."


def activate_version(version_id: int, activation_comment: str = None):
    """
    Активирует версию, обновляет ее комментарий и готовит данные для email.
    """
    planning_session = get_planning_session()  # <--- ДОБАВЛЕНО
    target_version = planning_session.query(planning_models.DiscountVersion).get(version_id)
    if not target_version: raise ValueError(f"Не найдена версия с ID: {version_id}")

    if activation_comment: target_version.comment = activation_comment
    old_active_version = planning_session.query(planning_models.DiscountVersion).filter_by(is_active=True).first()
    if old_active_version: old_active_version.is_active = False

    target_version.is_active = True
    target_version.was_ever_activated = True
    planning_session.commit()

    if old_active_version:
        comments_data = json.loads(target_version.changes_summary_json) if target_version.changes_summary_json else None
        summary_html = _generate_version_comparison_summary(old_active_version, target_version, comments_data=comments_data)
        subject = f"ApartmentFinder: Активирована новая версия скидок №{target_version.version_number}"
        return {'subject': subject, 'html_body': summary_html}
    return None