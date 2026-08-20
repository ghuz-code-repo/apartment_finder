# app/services/cancellation_service.py

from datetime import datetime
from app.core.db_utils import get_default_session, get_mysql_session
from app.models.registry_models import CancellationRegistry
from app.models.estate_models import EstateSell, EstateHouse, EstateDeal
from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
import pandas as pd
import io


def generate_cancellations_excel():
    """Генерирует Excel-файл без столбцов локации, но с параметрами расторжения."""
    data = get_cancellations()
    if not data:
        return None

    df = pd.DataFrame(data)

    # Преобразование булевых значений для выгрузки
    status_map = {True: 'Да', False: '-'}
    df['is_free'] = df['is_free'].map(status_map)
    df['is_no_money'] = df['is_no_money'].map(status_map)
    df['is_change_object'] = df['is_change_object'].map(status_map)

    # Обновленный маппинг: удалены Дом, Подъезд, Номер помещения
    column_mapping = {
        'sell_id': 'ID Объекта',
        'cancellation_date': 'Дата расторжения',
        'complex': 'ЖК',
        'type': 'Тип',
        'floor': 'Этаж',
        'rooms': 'Комн.',
        'area': 'Площадь',
        'is_free': 'Свободно',
        'is_no_money': 'Без денег',
        'is_change_object': 'Смена объекта',
        'contract_number': 'Номер договора',
        'contract_date': 'Дата договора',
        'contract_sum': 'Сумма договора'
    }

    df = df[list(column_mapping.keys())].rename(columns=column_mapping)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Реестр расторжений')
    output.seek(0)
    return output

def get_cancellations():
    default_session = get_default_session()
    cancellations = default_session.query(CancellationRegistry).order_by(desc(CancellationRegistry.created_at)).all()

    result = []
    for canc in cancellations:
        # Приоритет ручным данным над сохраненными при создании
        display_num = canc.manual_number if canc.manual_number else (canc.contract_number or '-')

        display_date = '-'
        if canc.manual_date:
            display_date = canc.manual_date.strftime('%d.%m.%Y')
        elif canc.contract_date:
            display_date = canc.contract_date.strftime('%d.%m.%Y')

        display_sum = canc.manual_sum if canc.manual_sum else (canc.contract_sum or 0)

        item = {
            'registry_id': canc.id,
            'sell_id': canc.estate_sell_id,
            'cancellation_date': canc.created_at.strftime('%d.%m.%Y'),
            'complex': canc.complex_name,
            'house': canc.house_name,
            'entrance': canc.entrance,
            'number': canc.number,
            'is_free': canc.is_free,
            'is_no_money': canc.is_no_money,
            'is_change_object': canc.is_change_object,
            'type': canc.cat_type,
            'floor': canc.floor,
            'rooms': canc.rooms,
            'area': canc.area,
            'contract_number': display_num,
            'contract_date': display_date,
            'contract_sum': display_sum,
            'manual_number_raw': canc.manual_number or '',
            'manual_date_raw': canc.manual_date.strftime('%Y-%m-%d') if canc.manual_date else '',
            'manual_sum_raw': canc.manual_sum or ''
        }
        result.append(item)
    return result


def _find_duplicate(session, sell_id, deal_id, contract_num):
    """Ищет уже внесённое расторжение того же события.

    Событие определяет сделка. Если сделки нет, опереться не на что: тогда
    отсекаем только точное совпадение по непустому номеру договора, а при
    пустом разрешаем внести — лишнюю запись пользователь удалит сам, а вот
    ложная блокировка не оставляет ему выхода.
    """
    query = session.query(CancellationRegistry).filter_by(estate_sell_id=sell_id)

    if deal_id is not None:
        exists = query.filter_by(estate_deal_id=deal_id).first()
        if exists:
            return exists
        if contract_num:
            # Записи, внесённые до появления estate_deal_id, ссылки на сделку
            # не имеют — их узнаём по номеру договора.
            return query.filter_by(estate_deal_id=None, contract_number=contract_num).first()
        return None

    if contract_num:
        return query.filter_by(contract_number=contract_num).first()
    return None


def add_cancellation(sell_id: int, is_free: bool = False, is_no_money: bool = False, is_change_object: bool = False):
    default_session = get_default_session()
    mysql_session = get_mysql_session()

    # 1. Получаем данные из MySQL с подгрузкой связей
    sell = mysql_session.query(EstateSell).options(
        joinedload(EstateSell.house),
        joinedload(EstateSell.deals)
    ).get(sell_id)

    if not sell:
        return False, f"Объект {sell_id} не найден в MySQL."

    # 2. Инициализируем переменные договора (всегда, чтобы избежать NameError)
    deal_id = None
    contract_num = None
    contract_date_obj = None
    contract_sum = 0

    if sell.deals:
        # Выбираем последнюю сделку по ID (самая актуальная)
        last_deal = max(sell.deals, key=lambda d: d.id)
        deal_id = last_deal.id
        # Оба поля — колонки модели, атрибут есть всегда. getattr с запасным
        # значением здесь не срабатывал и отдавал None, когда основной договор
        # ещё не оформлен: нужен номер предварительного.
        contract_num = last_deal.agreement_number or last_deal.arles_agreement_num
        contract_date_obj = last_deal.agreement_date or last_deal.preliminary_date
        contract_sum = last_deal.deal_sum or 0

    # 3. Проверка на дубликат. Один объект расторгается много раз, поэтому
    # сравниваем не объект, а сделку: она и есть событие расторжения. Номер
    # договора для этого не годился — у брони он пустой, и второе расторжение
    # с пустым номером совпадало с первым.
    exists = _find_duplicate(default_session, sell_id, deal_id, contract_num)
    if exists:
        return False, (f"Это расторжение уже внесено в реестр "
                       f"(запись №{exists.id} от {exists.created_at.strftime('%d.%m.%Y')}). "
                       f"Чтобы внести повторное расторжение объекта, дождитесь "
                       f"новой сделки по нему в MacroCRM.")

    # 4. Создаем запись со всеми заполненными полями
    new_cancellation = CancellationRegistry(
        estate_sell_id=sell_id,
        estate_deal_id=deal_id,
        complex_name=sell.house.complex_name if sell.house else '-',
        house_name=sell.house.name if sell.house else '-',
        entrance=getattr(sell, 'geo_house_entrance', '-'),
        number=getattr(sell, 'geo_flatnum', sell.estate_sell_category),
        cat_type=sell.estate_sell_category,
        floor=sell.estate_floor,
        rooms=sell.estate_rooms,
        is_free=is_free,
        is_no_money=is_no_money,
        is_change_object=is_change_object,
        area=sell.estate_area,
        contract_number=contract_num,
        contract_date=contract_date_obj,
        contract_sum=contract_sum
    )

    try:
        default_session.add(new_cancellation)
        default_session.commit()
        return True, "Объект успешно добавлен в реестр расторжений."
    except IntegrityError:
        # Сюда приходит база со старым UNIQUE на estate_sell_id: в модели его
        # нет, повторное расторжение одного объекта разрешено. Схему чинит
        # repair_cancellation_registry() на старте, здесь — понятный текст
        # вместо сырого 'UNIQUE constraint failed'.
        default_session.rollback()
        return False, (f"Объект {sell_id} уже есть в реестре, а база не принимает "
                       f"повторное расторжение. Перезапустите сервис: схема "
                       f"обновляется при старте.")
    except Exception as e:
        default_session.rollback()
        return False, f"Ошибка сохранения: {e}"


def delete_cancellation(registry_id: int):
    """Удаляет запись из реестра расторжений."""
    default_session = get_default_session()
    item = default_session.query(CancellationRegistry).get(registry_id)
    if item:
        default_session.delete(item)
        default_session.commit()
        return True
    return False


def update_manual_data(registry_id: int, number: str, date_str: str, sum_val: float,
                       is_free: bool, is_no_money: bool, is_change_object: bool):
    """
    Обновляет ручные поля (manual_*) для записи реестра.
    Используется, если автоматические данные из MySQL отсутствуют.
    """
    default_session = get_default_session()
    item = default_session.query(CancellationRegistry).get(registry_id)
    if not item:
        return False, "Запись не найдена"

    try:
        # Обновляем поля. Если пришла пустая строка - ставим None
        item.manual_number = number if number else None

        if date_str:
            item.manual_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            item.manual_date = None

        item.manual_sum = sum_val if sum_val else None
        item.is_free = is_free
        item.is_no_money = is_no_money
        item.is_change_object = is_change_object
        default_session.commit()
        return True, "Данные успешно обновлены"
    except Exception as e:
        default_session.rollback()
        return False, f"Ошибка сохранения: {e}"