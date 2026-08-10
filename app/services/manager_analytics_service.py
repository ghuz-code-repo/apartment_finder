# app/services/manager_analytics_service.py

from sqlalchemy import func, extract
from collections import defaultdict
from ..core.db_utils import get_mysql_session
from ..models.auth_models import SalesManager
from ..models.funnel_models import EstateBuysStatusLog
from ..models.estate_models import EstateDeal


def get_manager_analytics_report(year: int, month: int, post_title: str = None):
    mysql_session = get_mysql_session()
    """
    Собирает аналитические данные по менеджерам за указанный период.
    """
    # ... (Блоки 1, 2 и 3 без изменений) ...
    manager_query = mysql_session.query(SalesManager)
    if post_title and post_title != 'all':
        manager_query = manager_query.filter(SalesManager.post_title == post_title)

    managers = manager_query.all()
    if not managers:
        return []

    def metric_scaffold():
        return {'count': 0, 'buy_ids': []}

    report_data = {
        manager.id: {
            "manager_id": manager.id,
            "manager_name": manager.full_name,
            "post_title": manager.post_title or 'Не указана',
            "bookings": metric_scaffold(),
            "deals_in_progress": metric_scaffold(),
            "deals_completed": metric_scaffold(),
            "deals_failed": metric_scaffold() # <-- НОВАЯ ОБЩАЯ МЕТРИКА
        } for manager in managers
    }
    manager_ids = list(report_data.keys())

    # 2. Подсчет "Броней" и сбор их ID
    bookings_query = mysql_session.query(
        EstateBuysStatusLog.manager_id,
        EstateBuysStatusLog.estate_buy_id
    ).filter(
        extract('year', EstateBuysStatusLog.log_date) == year,
        extract('month', EstateBuysStatusLog.log_date) == month,
        EstateBuysStatusLog.status_to_name == 'Бронь',
        EstateBuysStatusLog.manager_id.in_(manager_ids)
    ).all()

    for manager_id, buy_id in bookings_query:
        if manager_id in report_data:
            report_data[manager_id]['bookings']['buy_ids'].append(buy_id)

    # 3. Атрибуция сделок по переходу "Подбор" -> "Бронь"
    target_statuses = ["Сделка в работе", "Сделка проведена", "Сделка расторгнута"]
    status_to_key_map = {
        "Сделка в работе": "deals_in_progress",
        "Сделка проведена": "deals_completed",
        "Сделка расторгнута": "deals_failed"  # <-- ИЗМЕНЕНИЕ
    }

    deal_events = mysql_session.query(
        EstateBuysStatusLog.estate_buy_id,
        EstateBuysStatusLog.status_to_name
    ).filter(
        extract('year', EstateBuysStatusLog.log_date) == year,
        extract('month', EstateBuysStatusLog.log_date) == month,
        EstateBuysStatusLog.status_to_name.in_(target_statuses)
    ).all()

    if deal_events:
        deal_buy_ids = list(set([event.estate_buy_id for event in deal_events]))
        full_history_logs = mysql_session.query(
            EstateBuysStatusLog.estate_buy_id,
            EstateBuysStatusLog.manager_id,
            EstateBuysStatusLog.status_to_name
        ).filter(
            EstateBuysStatusLog.estate_buy_id.in_(deal_buy_ids)
        ).order_by(
            EstateBuysStatusLog.estate_buy_id,
            EstateBuysStatusLog.log_date
        ).all()

        history_by_buy_id = defaultdict(list)
        for log in full_history_logs:
            history_by_buy_id[log.estate_buy_id].append(log)

        responsible_manager_map = {}
        for buy_id, history in history_by_buy_id.items():
            for i in range(1, len(history)):
                prev_log = history[i - 1]
                current_log = history[i]
                if prev_log.status_to_name == 'Подбор' and current_log.status_to_name == 'Бронь' and current_log.manager_id:
                    responsible_manager_map[buy_id] = current_log.manager_id

        for buy_id, status_name in deal_events:
            manager_id = responsible_manager_map.get(buy_id)
            if manager_id and manager_id in manager_ids:
                key = status_to_key_map.get(status_name)
                if key:
                    report_data[manager_id][key]['buy_ids'].append(buy_id)

    # 4. Подсчет "Сделок отменена"
    canceled_deals_query = mysql_session.query(
        EstateDeal.deal_manager_id,
        func.count(EstateDeal.id)
    ).filter(
        extract('year', EstateDeal.date_modified) == year,
        extract('month', EstateDeal.date_modified) == month,
        # --- ИЗМЕНЕНИЕ: Ищем оба статуса ---
        EstateDeal.deal_status_name.in_(['Не понравилось', 'Сделка отменена']),
        EstateDeal.deal_sum != 0,
        # --- КОНЕЦ ИЗМЕНЕНИЙ ---
        EstateDeal.deal_manager_id.in_(manager_ids)
    ).group_by(EstateDeal.deal_manager_id).all()

    for manager_id, count in canceled_deals_query:
        if manager_id in report_data:
            report_data[manager_id]['deals_failed']['count'] += count

    # 5. Финальный подсчет количества из списков ID
    for data in report_data.values():
        for metric in ["bookings", "deals_in_progress", "deals_completed", "deals_failed"]:
            unique_ids = list(set(data[metric]['buy_ids']))
            data[metric]['buy_ids'] = unique_ids
            if metric != 'deals_failed':
                data[metric]['count'] = len(unique_ids)
            else:
                data[metric]['count'] += len(unique_ids)

    final_list = sorted(report_data.values(), key=lambda x: x['manager_name'])
    return final_list


def get_yearly_manager_analytics(manager_id: int, year: int):
    """
    Собирает помесячную статистику для одного менеджера за весь год.
    """
    monthly_data = []
    # Запускаем основную логику для каждого месяца
    for month in range(1, 13):
        # Получаем полный отчет за месяц
        full_month_report = get_manager_analytics_report(year, month)
        # Находим в нем данные по нашему менеджеру
        manager_data = next((row for row in full_month_report if row.get("manager_id") == manager_id), None)

        if manager_data:
            monthly_data.append(manager_data)
        else:
            # Если данных нет, добавляем пустую структуру, чтобы не ломать график
            monthly_data.append({
                "manager_id": manager_id,
                "month": month,
                "bookings": {'count': 0},
                "deals_in_progress": {'count': 0},
                "deals_completed": {'count': 0},
                "deals_terminated": {'count': 0},
                "deals_canceled": {'count': 0}
            })

    # Считаем годовые итоги
    annual_totals = {
        "bookings": sum(m['bookings']['count'] for m in monthly_data),
        "deals_in_progress": sum(m['deals_in_progress']['count'] for m in monthly_data),
        "deals_completed": sum(m['deals_completed']['count'] for m in monthly_data),
        "deals_failed": sum(m['deals_failed']['count'] for m in monthly_data),
    }

    return monthly_data, annual_totals