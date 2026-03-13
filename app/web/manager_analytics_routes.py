# app/web/manager_analytics_routes.py

from flask import Blueprint, render_template, request
from ..core.decorators import permission_required, login_required
from datetime import date
from app.core.decorators import permission_required
from app.services import manager_analytics_service, funnel_service  # Добавлен funnel_service
from app.models.auth_models import SalesManager
from ..core.db_utils import get_mysql_session

manager_analytics_bp = Blueprint('manager_analytics', __name__, template_folder='templates')


@manager_analytics_bp.route('/report')
@login_required
@permission_required('view_manager_report')
def show_report():
    today = date.today()
    year = request.args.get('year', today.year, type=int)
    month = request.args.get('month', today.month, type=int)
    selected_post = request.args.get('post_title', 'all')

    show_non_zero = request.args.get('show_non_zero') == 'on'
    sort_by = request.args.get('sort_by', 'manager_name')
    sort_order = request.args.get('sort_order', 'asc')

    report_data = manager_analytics_service.get_manager_analytics_report(year, month, post_title=selected_post)

    if show_non_zero:
        report_data = [
            row for row in report_data if
            (row['bookings']['count'] +
             row['deals_in_progress']['count'] +
             row['deals_completed']['count'] +
             row['deals_failed']['count']) > 0
        ]

    # --- ИСПРАВЛЕНИЕ ЗДЕСЬ ---
    if sort_by in ['manager_name', 'post_title']:
        report_data.sort(key=lambda row: row[sort_by], reverse=(sort_order == 'desc'))
    # Обновляем список ключей, добавляя 'deals_failed' и убирая старые
    elif sort_by in ['bookings', 'deals_in_progress', 'deals_completed', 'deals_failed']:
        report_data.sort(key=lambda row: row[sort_by]['count'], reverse=(sort_order == 'desc'))
    # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

    # Расчет итогов ПОСЛЕ фильтрации
    totals = {
        "bookings": {"count": sum(r['bookings']['count'] for r in report_data),
                     "buy_ids": [id for r in report_data for id in r['bookings']['buy_ids']]},
        "deals_in_progress": {"count": sum(r['deals_in_progress']['count'] for r in report_data),
                              "buy_ids": [id for r in report_data for id in r['deals_in_progress']['buy_ids']]},
        "deals_completed": {"count": sum(r['deals_completed']['count'] for r in report_data),
                            "buy_ids": [id for r in report_data for id in r['deals_completed']['buy_ids']]},
        "deals_failed": {"count": sum(r['deals_failed']['count'] for r in report_data),
                         "buy_ids": [id for r in report_data for id in r['deals_failed']['buy_ids']]}
    }

    for key in totals:
        totals[key]['buy_ids'] = list(set(totals[key]['buy_ids']))
    mysql_session = get_mysql_session()
    posts_query = mysql_session.query(SalesManager.post_title).filter(
        SalesManager.post_title.isnot(None)).distinct().order_by(SalesManager.post_title).all()
    all_posts = [post[0] for post in posts_query]

    return render_template(
        'reports/manager_analytics_report.html',
        title="Аналитика по менеджерам",
        data=report_data,
        totals=totals,
        years=[today.year - 1, today.year, today.year + 1],
        months=range(1, 13),
        all_posts=all_posts,
        selected_year=year,
        selected_month=month,
        selected_post=selected_post,
        show_non_zero=show_non_zero,
        sort_by=sort_by,
        sort_order=sort_order
    )


@manager_analytics_bp.route('/yearly-report')
@login_required
@permission_required('view_manager_report')
def yearly_report():
    today = date.today()
    # Получаем параметры из формы
    selected_year = request.args.get('year', today.year, type=int)
    mysql_session = get_mysql_session()  # <--- ДОБАВЛЕНО

    selected_manager_id = request.args.get('manager_id', type=int)

    all_managers = mysql_session.query(SalesManager).order_by(SalesManager.full_name).all()

    report_data = None
    annual_totals = None
    selected_manager = None

    if selected_manager_id:
        report_data, annual_totals = manager_analytics_service.get_yearly_manager_analytics(selected_manager_id,
                                                                                            selected_year)
        selected_manager = mysql_session.query(SalesManager).get(selected_manager_id)

    return render_template(
        'reports/yearly_manager_report.html',
        title="Годовой отчет по менеджеру",
        all_managers=all_managers,
        selected_year=selected_year,
        selected_manager_id=selected_manager_id,
        selected_manager=selected_manager,
        report_data=report_data,
        annual_totals=annual_totals,
        years=[today.year - 1, today.year, today.year + 1],
        active_tab='yearly'  # <-- Указываем активную вкладку
    )


# НОВЫЙ МАРШРУТ для отображения списка заявок
@manager_analytics_bp.route('/leads-list')
@login_required
@permission_required('view_manager_report')
def leads_list():
    ids_str = request.args.get('ids', '')
    title = request.args.get('title', 'Список заявок')

    leads = funnel_service.get_leads_details_by_ids(ids_str)

    return render_template(
        'reports/leads_list.html',
        title=title,
        leads=leads
    )