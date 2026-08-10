# app/services/obligation_service.py

from datetime import date, datetime
from sqlalchemy import func, extract, or_
from ..core.db_utils import get_planning_session, get_mysql_session
from app.models.finance_models import ProjectObligation
from app.models.estate_models import EstateDeal, EstateSell, EstateHouse
from app.services import currency_service
from app.models.planning_models import PropertyType # <-- Импортируем PropertyType

# Константы для статусов
DEAL_SOLD_STATUSES = ["Сделка в работе", "Сделка проведена"]
REMAINDER_STATUSES = ["Маркетинговый резерв", "Подбор"]

def get_all_obligations():
    """Возвращает список всех сохраненных обязательств (проект, тип, сумма USD)."""
    planning_session = get_planning_session()
    obligations = planning_session.query(
        ProjectObligation.id,
        ProjectObligation.project_name,
        ProjectObligation.property_type, # <-- Добавили тип
        ProjectObligation.amount
    ).filter(ProjectObligation.currency == 'USD').order_by(
        ProjectObligation.project_name, ProjectObligation.property_type # Сортируем и по типу
    ).all()
    return [
        {'id': obl.id,
         'project_name': obl.project_name,
         'property_type': obl.property_type, # <-- Добавили тип
         'amount_usd': obl.amount}
        for obl in obligations
    ]

def add_obligation(project_name: str, property_type_str: str, amount_usd: float, comment: str = None):
    planning_session = get_planning_session()
    """Добавляет новое или обновляет существующее обязательство по проекту и типу недвижимости."""
    if not project_name or not property_type_str or amount_usd <= 0:
        raise ValueError("Не указан проект, тип недвижимости или сумма обязательства некорректна.")

    # Проверяем валидность типа недвижимости
    valid_types = [pt.value for pt in PropertyType]
    if property_type_str not in valid_types:
        raise ValueError(f"Недопустимый тип недвижимости: {property_type_str}")

    # Ищем по проекту И типу недвижимости
    obligation = planning_session.query(ProjectObligation).filter_by(
        project_name=project_name,
        property_type=property_type_str,
        currency='USD'
    ).first()

    if obligation:
        obligation.amount = amount_usd
        obligation.comment = comment
        obligation.due_date = date.today()
        print(f"Обновлено обязательство для '{project_name}' ({property_type_str}): {amount_usd} USD")
    else:
        new_obligation = ProjectObligation(
            project_name=project_name,
            property_type=property_type_str, # <-- Сохраняем тип
            amount=amount_usd,
            currency='USD',
            obligation_type='Financial Target',
            due_date=date.today(),
            status='Active',
            comment=comment
        )
        planning_session.add(new_obligation)
        print(f"Добавлено новое обязательство для '{project_name}' ({property_type_str}): {amount_usd} USD")

    planning_session.commit()


def calculate_required_avg_price(project_name: str, property_type_str: str, start_date_str: str):
    planning_session = get_planning_session()  # <--- ДОБАВЛЕНО
    mysql_session = get_mysql_session()
    """Рассчитывает требуемую среднюю цену продажи остатков в USD/м² для конкретного типа недвижимости."""
    if not project_name or not property_type_str or not start_date_str:
        return {'error': "Необходимо выбрать проект, тип недвижимости и указать дату начала."}

    # Проверяем валидность типа недвижимости
    valid_types = [pt.value for pt in PropertyType]
    if property_type_str not in valid_types:
         return {'error': f"Недопустимый тип недвижимости: {property_type_str}"}

    try:
        start_date = date.fromisoformat(start_date_str)
    except ValueError:
        return {'error': "Неверный формат даты начала."}

    # 1. Найти сумму обязательства (USD) для проекта и типа
    obligation = planning_session.query(ProjectObligation).filter_by(
        project_name=project_name,
        property_type=property_type_str, # <-- Фильтр по типу
        currency='USD'
    ).first()
    if not obligation:
        return {'error': f"Обязательство для проекта '{project_name}' ({property_type_str}) не найдено."}
    target_amount_usd = obligation.amount

    # 2. Рассчитать общий объем контрактации (UZS) с даты начала ДЛЯ ЭТОГО ТИПА
    effective_date = func.coalesce(EstateDeal.agreement_date, EstateDeal.preliminary_date)
    total_volume_uzs_query = mysql_session.query(
        func.sum(EstateDeal.deal_sum)
    ).join(EstateSell, EstateDeal.estate_sell_id == EstateSell.id)\
     .join(EstateHouse, EstateSell.house_id == EstateHouse.id)\
     .filter(
        EstateHouse.complex_name == project_name,
        EstateSell.estate_sell_category == property_type_str, # <-- Фильтр по типу
        EstateDeal.deal_status_name.in_(DEAL_SOLD_STATUSES),
        effective_date >= start_date
    )
    total_volume_uzs = total_volume_uzs_query.scalar() or 0.0

    # 3. Конвертировать объем в USD
    usd_rate = currency_service.get_current_effective_rate()
    if not usd_rate or usd_rate <= 0:
        return {'error': "Не удалось получить актуальный курс USD."}
    total_volume_usd = total_volume_uzs / usd_rate

    # 4. Рассчитать остаток обязательства (USD)
    remaining_obligation_usd = target_amount_usd - total_volume_usd

    if remaining_obligation_usd <= 0:
        return {
            'target_amount_usd': target_amount_usd,
            'total_volume_usd': total_volume_usd,
            'remaining_obligation_usd': remaining_obligation_usd,
            'total_remaining_area': 0,
            'required_avg_price_usd': 0,
            'message': f'Обязательство по {property_type_str} уже выполнено или перевыполнено за счет сделок с указанной даты.'
        }

    # 5. Рассчитать суммарную площадь остатков (м²) ДЛЯ ЭТОГО ТИПА
    total_remaining_area_query = mysql_session.query(
        func.sum(EstateSell.estate_area)
    ).join(EstateHouse, EstateSell.house_id == EstateHouse.id)\
     .filter(
        EstateHouse.complex_name == project_name,
        EstateSell.estate_sell_category == property_type_str, # <-- Фильтр по типу
        EstateSell.estate_sell_status_name.in_(REMAINDER_STATUSES),
        EstateSell.estate_area.isnot(None),
        EstateSell.estate_area > 0
    )
    total_remaining_area = total_remaining_area_query.scalar() or 0.0

    # 6. Рассчитать требуемую среднюю цену (USD/м²)
    if total_remaining_area <= 0:
        return {
            'target_amount_usd': target_amount_usd,
            'total_volume_usd': total_volume_usd,
            'remaining_obligation_usd': remaining_obligation_usd,
            'total_remaining_area': 0,
            'required_avg_price_usd': None,
            'error': f"Нет доступных остатков типа '{property_type_str}' для продажи в проекте '{project_name}'."
        }

    required_avg_price_usd = remaining_obligation_usd / total_remaining_area

    return {
        'project_name': project_name,
        'property_type': property_type_str, # <-- Добавили тип в результат
        'start_date': start_date_str,
        'target_amount_usd': target_amount_usd,
        'total_volume_usd': total_volume_usd,
        'remaining_obligation_usd': remaining_obligation_usd,
        'total_remaining_area': total_remaining_area,
        'required_avg_price_usd': required_avg_price_usd
    }

def delete_obligation(obligation_id: int):
    """Удаляет обязательство по ID."""
    planning_session = get_planning_session()  # <--- ДОБАВЛЕНО
    obligation = planning_session.get(ProjectObligation, obligation_id)
    if obligation:
        if obligation.currency == 'USD' and obligation.obligation_type == 'Financial Target':
             planning_session.delete(obligation)
             planning_session.commit()
             # Добавим тип в сообщение
             return True, f"Обязательство ID {obligation_id} ({obligation.project_name} - {obligation.property_type}) удалено."
        else:
            return False, f"Запись ID {obligation_id} не является финансовым обязательством по проекту."
    else:
        return False, f"Обязательство с ID {obligation_id} не найдено."