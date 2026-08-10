# app/services/refund_service.py

from sqlalchemy import func, extract
from ..core.db_utils import get_mysql_session
from ..models.finance_models import FinanceOperation
from ..models.estate_models import EstateSell, EstateHouse


def get_refund_report_data(year: int, month: int):
    """
    Получает данные по плановым и фактическим возвратам в разрезе проектов.
    """
    session = get_mysql_session()

    # 1. Запрос Плановых возвратов (Статус: К оплате)
    # Плановые суммы обычно смотрят по дате 'date_to' (срок платежа)
    planned_query = session.query(
        EstateHouse.complex_name,
        func.sum(FinanceOperation.summa).label('amount')
    ).join(EstateSell, FinanceOperation.estate_sell_id == EstateSell.id) \
        .join(EstateHouse, EstateSell.house_id == EstateHouse.id) \
        .filter(
        FinanceOperation.payment_type == "Возврат при уменьшении стоимости",
        FinanceOperation.status_name == "К оплате",
        extract('year', FinanceOperation.date_to) == year,
        extract('month', FinanceOperation.date_to) == month
    ).group_by(EstateHouse.complex_name).all()

    # 2. Запрос Фактических возвратов (Статус: Проведено)
    # Фактические суммы смотрят по дате 'date_added' (дата проводки)
    actual_query = session.query(
        EstateHouse.complex_name,
        func.sum(FinanceOperation.summa).label('amount')
    ).join(EstateSell, FinanceOperation.estate_sell_id == EstateSell.id) \
        .join(EstateHouse, EstateSell.house_id == EstateHouse.id) \
        .filter(
        FinanceOperation.payment_type == "Возврат при уменьшении стоимости",
        FinanceOperation.status_name == "Проведено",
        extract('year', FinanceOperation.date_added) == year,
        extract('month', FinanceOperation.date_added) == month
    ).group_by(EstateHouse.complex_name).all()

    # Объединяем данные в структуру для таблицы
    report_data = {}

    for complex_name, amount in planned_query:
        report_data[complex_name] = {'planned': amount, 'actual': 0}

    for complex_name, amount in actual_query:
        if complex_name not in report_data:
            report_data[complex_name] = {'planned': 0, 'actual': amount}
        else:
            report_data[complex_name]['actual'] = amount

    session.close()
    return report_data