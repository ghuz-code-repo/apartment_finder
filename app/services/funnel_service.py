# app/services/funnel_service.py

from collections import Counter
from collections import defaultdict
from datetime import date
from sqlalchemy import func
from ..core.db_utils import get_mysql_session
from ..models.funnel_models import EstateBuy, EstateBuysStatusLog



def _format_status(status, custom_status):
    status = (status or "").strip()
    custom_status = (custom_status or "").strip()
    if not status: return "Без статуса"
    return f"{status}: {custom_status}" if custom_status else status


def get_target_funnel_metrics(start_date_str: str, end_date_str: str):
    mysql_session = get_mysql_session()
    """
    Рассчитывает разделение на целевые/нецелевые и ключевые показатели конверсии.
    (С УТОЧНЕНИЕМ: Сделка = 'Сделка в работе' + 'Сделка проведена')
    """
    # === Шаги 1-2: Сбор когорты и логов (без изменений) ===
    cohort_query = mysql_session.query(EstateBuy.id)
    try:
        start_date = date.fromisoformat(start_date_str)
        cohort_query = cohort_query.filter(EstateBuy.date_added >= start_date)
    except (ValueError, TypeError):
        pass
    try:
        end_date = date.fromisoformat(end_date_str)
        cohort_query = cohort_query.filter(EstateBuy.date_added <= end_date)
    except (ValueError, TypeError):
        pass

    # --- ИЗМЕНЕНИЕ: Используем подзапрос ---
    total_leads_count = cohort_query.count()

    if not total_leads_count:
        return {'total_leads': 0}

    logs = mysql_session.query(
        EstateBuysStatusLog.estate_buy_id,
        EstateBuysStatusLog.status_to_name,
        EstateBuysStatusLog.status_custom_to_name
    ).filter(EstateBuysStatusLog.estate_buy_id.in_(cohort_query)).all() # <-- Передаем сам запрос

    # --- ИЗМЕНЕНИЕ: Получаем ID для дальнейшей обработки ---
    initial_cohort_ids = {row[0] for row in cohort_query.all()}


    statuses_by_lead = {}
    for lead_id, status, custom_status in logs:
        if lead_id not in statuses_by_lead: statuses_by_lead[lead_id] = set()
        statuses_by_lead[lead_id].add(((status or '').strip(), (custom_status or '').strip()))

    def lead_has_status(lead_id, status_name, custom_status_name=None):
        for s, cs in statuses_by_lead.get(lead_id, set()):
            if s == status_name and (custom_status_name is None or cs == custom_status_name):
                return True
        return False

    # === Шаг 3: Разделение на Целевые/Нецелевые и Сделки ===
    nontarget_ids = {pid for pid in initial_cohort_ids if lead_has_status(pid, 'Нецелевой')}
    target_ids = initial_cohort_ids - nontarget_ids
    # --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
    deal_ids = {pid for pid in target_ids if lead_has_status(pid, 'Сделка в работе') or lead_has_status(pid, 'Сделка проведена')}

    # === Шаг 4: Расчет ключевых конверсий (С ИЗМЕНЕНИЯМИ) ===

    # --- Конверсии из "Подбора" ---
    podbor_base_ids = {pid for pid in target_ids if lead_has_status(pid, 'Подбор')}
    podbor_to_otkaz_ids = {pid for pid in podbor_base_ids if lead_has_status(pid, 'Отказ')}
    podbor_to_vstrecha_ids = {pid for pid in podbor_base_ids if lead_has_status(pid, 'Подбор', 'Назначенная встреча')}
    podbor_to_bron_ids = {pid for pid in podbor_base_ids if lead_has_status(pid, 'Бронь')}
    podbor_moved_on_ids = podbor_to_otkaz_ids | podbor_to_vstrecha_ids | podbor_to_bron_ids
    stuck_in_podbor_count = len(podbor_base_ids) - len(podbor_moved_on_ids)

    # --- Конверсии из "Назначенной встречи" ---
    vstrecha_base_ids = {pid for pid in target_ids if lead_has_status(pid, 'Подбор', 'Назначенная встреча')}
    vstrecha_to_sostoyalas_ids = {pid for pid in vstrecha_base_ids if lead_has_status(pid, 'Подбор', 'Визит состоялся')}
    vstrecha_to_nesostoyalas_ids = {pid for pid in vstrecha_base_ids if lead_has_status(pid, 'Подбор', 'Визит не состоялся')}
    vstrecha_to_bron_ids = {pid for pid in vstrecha_base_ids if lead_has_status(pid, 'Бронь')}
    vstrecha_to_otkaz_ids = {pid for pid in vstrecha_base_ids if lead_has_status(pid, 'Отказ')}
    vstrecha_moved_on_ids = vstrecha_to_sostoyalas_ids | vstrecha_to_nesostoyalas_ids | vstrecha_to_bron_ids | vstrecha_to_otkaz_ids
    stuck_in_vstrecha_count = len(vstrecha_base_ids) - len(vstrecha_moved_on_ids)

    # --- Конверсии из "Визит состоялся" ---
    vizit_sostoyalsya_base_ids = {pid for pid in vstrecha_base_ids if lead_has_status(pid, 'Подбор', 'Визит состоялся')}
    vizit_to_bron_ids = {pid for pid in vizit_sostoyalsya_base_ids if lead_has_status(pid, 'Бронь')}
    vizit_to_otkaz_ids = {pid for pid in vizit_sostoyalsya_base_ids if lead_has_status(pid, 'Отказ')}
    vizit_moved_on_ids = vizit_to_bron_ids | vizit_to_otkaz_ids
    stuck_in_vizit_count = len(vizit_sostoyalsya_base_ids) - len(vizit_moved_on_ids)

    # --- Конверсии из "Брони" ---
    bron_base_ids = {pid for pid in target_ids if lead_has_status(pid, 'Бронь')}
    # --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
    bron_to_sdelka_ids = {pid for pid in bron_base_ids if lead_has_status(pid, 'Сделка в работе') or lead_has_status(pid, 'Сделка проведена')}
    bron_to_otkaz_ids = {pid for pid in bron_base_ids if lead_has_status(pid, 'Отказ')}
    bron_moved_on_ids = bron_to_sdelka_ids | bron_to_otkaz_ids
    stuck_in_bron_count = len(bron_base_ids) - len(bron_moved_on_ids)


    # === Шаг 5: Сборка итогового результата (С ИЗМЕНЕНИЯМИ) ===
    results = {
        'total_leads': total_leads_count,
        'nontarget_leads': {'count': len(nontarget_ids)},
        'target_leads': {'count': len(target_ids)},
        'deals': {'count': len(deal_ids)},
        'metrics': {
            'from_podbor': {
                'base_count': len(podbor_base_ids),
                'to_otkaz': len(podbor_to_otkaz_ids),
                'to_vstrecha': len(podbor_to_vstrecha_ids),
                'to_bron': len(podbor_to_bron_ids),
                'stuck': stuck_in_podbor_count
            },
            'from_vstrecha': {
                'base_count': len(vstrecha_base_ids),
                'to_sostoyalas': len(vstrecha_to_sostoyalas_ids),
                'to_nesostoyalas': len(vstrecha_to_nesostoyalas_ids),
                'to_bron': len(vstrecha_to_bron_ids),
                'to_otkaz': len(vstrecha_to_otkaz_ids),
                'stuck': stuck_in_vstrecha_count
            },
            'from_vizit': {
                'base_count': len(vizit_sostoyalsya_base_ids),
                'to_bron': len(vizit_to_bron_ids),
                'to_otkaz': len(vizit_to_otkaz_ids),

                'stuck': stuck_in_vizit_count
            },
            'from_bron': {
                'base_count': len(bron_base_ids),
                'to_sdelka': len(bron_to_sdelka_ids),
                'to_otkaz': len(bron_to_otkaz_ids),
                'stuck': stuck_in_bron_count,
            }
        }
    }
    return results

def finalize_tree_with_ids(node, threshold_percent=1.0):
    """
    Рекурсивно обходит дерево, группируя редкие ветки и агрегируя их ID,
    преобразует дочерние узлы в отсортированный список и добавляет поле 'count'.
    """
    node['count'] = len(node.get('ids', []))

    if not node.get('children'):
        node['children'] = []
        return

    for child_node in node['children'].values():
        finalize_tree_with_ids(child_node, threshold_percent)

    children_list = list(node['children'].values())
    threshold_count = (node['count'] * threshold_percent) / 100.0

    main_children = [child for child in children_list if child['count'] >= threshold_count]
    other_children = [child for child in children_list if child['count'] < threshold_count]

    if len(other_children) > 1:
        other_count = sum(child['count'] for child in other_children)
        other_ids = [id for child in other_children for id in child.get('ids', [])]
        other_node = {
            'name': 'Прочие пути',
            'count': other_count,
            'ids': other_ids,
            'children': []
        }
        main_children.append(other_node)
    else:
        main_children.extend(other_children)

    node['children'] = sorted(main_children, key=lambda x: x['count'], reverse=True)


def get_funnel_data(start_date_str: str, end_date_str: str):
    mysql_session = get_mysql_session()
    """
    Строит полное дерево путей заявок, ВКЛЮЧАЯ ID ЗАЯВОК в каждом узле.
    """
    # === Шаг 1: Когорта по ДАТЕ СОЗДАНИЯ заявки ===
    cohort_query = mysql_session.query(EstateBuy.id)
    if start_date_str:
        try:
            start_date = date.fromisoformat(start_date_str)
            cohort_query = cohort_query.filter(EstateBuy.date_added >= start_date)
        except (ValueError, TypeError):
            pass
    if end_date_str:
        try:
            end_date = date.fromisoformat(end_date_str)
            cohort_query = cohort_query.filter(EstateBuy.date_added <= end_date)
        except (ValueError, TypeError):
            pass

    # --- ИЗМЕНЕНИЕ: Не загружаем ID в память, оставляем как объект запроса ---
    total_leads = cohort_query.count()
    if not total_leads:
        return {'name': 'Заявки, созданные за период', 'count': 0, 'ids': [], 'children': []}, {}

    # === Шаг 2: Получаем все логи для когорты, используя подзапрос ===
    logs = mysql_session.query(
        EstateBuysStatusLog.estate_buy_id,
        EstateBuysStatusLog.status_to_name,
        EstateBuysStatusLog.status_custom_to_name
    ).filter(EstateBuysStatusLog.estate_buy_id.in_(cohort_query)).order_by(  # <-- Передаем сам запрос
        EstateBuysStatusLog.estate_buy_id, EstateBuysStatusLog.log_date
    ).all()

    # === Шаг 3: Восстанавливаем путь для каждой заявки ===
    paths_by_buy_id = defaultdict(list)
    for log in logs:
        formatted_status = _format_status(log.status_to_name, log.status_custom_to_name)
        if not paths_by_buy_id[log.estate_buy_id] or paths_by_buy_id[log.estate_buy_id][-1] != formatted_status:
            paths_by_buy_id[log.estate_buy_id].append(formatted_status)

    # --- ИЗМЕНЕНИЕ: Получаем все ID когорты для корневого узла дерева ---
    all_cohort_ids = [row[0] for row in cohort_query.all()]

    # === Шаг 4: Строим древовидную структуру С ID ===
    tree = {'name': 'Заявки, созданные за период', 'ids': all_cohort_ids, 'children': {}}
    for buy_id, path in paths_by_buy_id.items():
        current_level = tree
        for stage in path:
            if stage not in current_level['children']:
                current_level['children'][stage] = {'name': stage, 'ids': [], 'children': {}}
            current_level['children'][stage]['ids'].append(buy_id)
            current_level = current_level['children'][stage]

    # === Шаг 5: Вызываем единую функцию для финальной обработки дерева ===
    finalize_tree_with_ids(tree, threshold_percent=1.0)

    return tree, {}


def get_dead_end_summary(start_date_str: str, end_date_str: str):
    mysql_session = get_mysql_session()
    """
    Анализирует когорту созданных заявок и находит их конечные статусы.
    (Эта функция остается без изменений)
    """
    # === Шаг 1: Когорта по ДАТЕ СОЗДАНИЯ заявки ===
    cohort_query = mysql_session.query(EstateBuy.id)
    try:
        start_date = date.fromisoformat(start_date_str)
        cohort_query = cohort_query.filter(EstateBuy.date_added >= start_date)
    except (ValueError, TypeError): pass
    try:
        end_date = date.fromisoformat(end_date_str)
        cohort_query = cohort_query.filter(EstateBuy.date_added <= end_date)
    except (ValueError, TypeError): pass

    cohort_subquery = cohort_query.subquery()
    trunk_count = mysql_session.query(func.count(cohort_subquery.c.id)).scalar() or 0
    if not trunk_count:
        return {'total_leads': 0, 'summary': [], 'chart_data': {}}

    # === Шаг 2: Получаем все логи для когорты, упорядоченные по времени ===
    logs = mysql_session.query(
        EstateBuysStatusLog.estate_buy_id,
        EstateBuysStatusLog.status_to_name,
        EstateBuysStatusLog.status_custom_to_name
    ).filter(EstateBuysStatusLog.estate_buy_id.in_(cohort_query)).order_by(
        EstateBuysStatusLog.estate_buy_id, EstateBuysStatusLog.log_date
    ).all()

    # === Шаг 3: Находим последний статус для каждой заявки ===
    final_statuses = {}
    for lead_id, status, custom_status in logs:
        final_statuses[lead_id] = _format_status(status, custom_status)

    # === Шаг 4: Считаем количество каждого конечного статуса ===
    dead_end_counts = Counter(final_statuses.values())

    # === Шаг 5: Формируем итоговые данные ===
    summary = sorted(
        [{'name': status, 'count': count} for status, count in dead_end_counts.items()],
        key=lambda x: x['count'],
        reverse=True
    )
    chart_labels = [item['name'] for item in summary[:10]]
    chart_values = [item['count'] for item in summary[:10]]

    return {
        'total_leads': trunk_count,
        'summary': summary,
        'chart_data': {'labels': chart_labels, 'values': chart_values}
    }


def get_leads_details_by_ids(lead_ids_str: str):
    """
    Получает детали (ID, дата создания) для списка ID заявок из строки.
    """
    try:
        lead_ids = [int(id) for id in lead_ids_str.split(',') if id.isdigit()]
    except (ValueError, AttributeError):
        return []
    if not lead_ids:
        return []

    mysql_session = get_mysql_session()  # <--- ДОБАВЛЕНО

    leads = mysql_session.query(  # <--- ИЗМЕНЕНО
        EstateBuy.id,
        EstateBuy.date_added
    ).filter(
        EstateBuy.id.in_(lead_ids)
    ).order_by(EstateBuy.id).all()
    return [{'id': lead.id, 'date_added': lead.date_added.strftime('%d.%m.%Y')} for lead in leads]