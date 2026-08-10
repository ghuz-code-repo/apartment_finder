# app/services/registry_service.py

from app.core.db_utils import get_default_session, get_mysql_session
from app.models.registry_models import DealRegistry, RegistryType
from app.models.estate_models import EstateSell, EstateHouse
from sqlalchemy import desc


def get_registry_items(registry_type_value: str):
    """
    Возвращает список объектов для конкретной вкладки.
    Склеивает данные из локальной базы (реестр) и удаленной (информация об объекте).
    """
    default_session = get_default_session()
    mysql_session = get_mysql_session()

    try:
        reg_type = RegistryType(registry_type_value)
    except ValueError:
        return []

    # 1. Получаем список ID из реестра
    registry_entries = default_session.query(DealRegistry).filter_by(
        registry_type=reg_type
    ).order_by(desc(DealRegistry.created_at)).all()

    if not registry_entries:
        return []

    # Создаем словарь {sell_id: entry_object}
    entries_map = {entry.estate_sell_id: entry for entry in registry_entries}
    sell_ids = list(entries_map.keys())

    # 2. Запрашиваем данные об этих объектах из MySQL
    sells = mysql_session.query(EstateSell).join(EstateHouse).filter(
        EstateSell.id.in_(sell_ids)
    ).all()

    # 3. Собираем итоговую структуру
    result = []
    # Проходимся по sells, чтобы данные были валидными
    for sell in sells:
        entry = entries_map.get(sell.id)
        if not entry:
            continue

        item = {
            'registry_id': entry.id,
            'sell_id': sell.id,
            'complex': sell.house.complex_name if sell.house else '-',
            'house': sell.house.name if sell.house else '-',
            'number': f"Кв/Пом {sell.estate_sell_category} (ID {sell.id})",
            'area': sell.estate_area,
            'price': sell.estate_price,
            'status': sell.estate_sell_status_name,
            'added_at': entry.created_at.strftime('%d.%m.%Y %H:%M'),

            # Добавляем данные по К2 (будут None для других типов, это ок)
            'k2_sum': entry.k2_sum,
            'crm_sum': entry.crm_sum
        }
        result.append(item)

    result.sort(key=lambda x: x['added_at'], reverse=True)
    return result


def add_to_registry(sell_id: int, registry_type_value: str, k2_sum: float = None, crm_sum: float = None):
    """
    Добавляет объект в реестр.
    Принимает опциональные аргументы k2_sum и crm_sum.
    """
    default_session = get_default_session()
    mysql_session = get_mysql_session()

    try:
        reg_type = RegistryType(registry_type_value)
    except ValueError:
        return False, "Неверный тип реестра"

    # Проверки (без изменений)
    sell = mysql_session.query(EstateSell).filter_by(id=sell_id).first()
    if not sell:
        return False, f"Объект с ID {sell_id} не найден."

    existing = default_session.query(DealRegistry).filter_by(
        estate_sell_id=sell_id,
        registry_type=reg_type
    ).first()

    if existing:
        return False, "Этот объект уже есть в данном реестре."

    # Создание записи с новыми полями
    new_entry = DealRegistry(
        estate_sell_id=sell_id,
        registry_type=reg_type,
        k2_sum=k2_sum,
        crm_sum=crm_sum
    )
    default_session.add(new_entry)
    default_session.commit()

    return True, "Объект успешно добавлен."


def remove_from_registry(registry_id: int):
    """Удаляет запись из реестра."""
    default_session = get_default_session()
    entry = default_session.query(DealRegistry).filter_by(id=registry_id).first()
    if entry:
        default_session.delete(entry)
        default_session.commit()
        return True
    return False