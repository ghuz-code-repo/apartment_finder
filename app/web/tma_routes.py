# app/web/tma_routes.py
import json
from flask import Blueprint, render_template, abort
from app.core.decorators import tma_auth_required
from app.services import data_service, project_dashboard_service, currency_service

tma_bp = Blueprint('tma', __name__)


@tma_bp.route('/dashboard')
@tma_auth_required
def dashboard():
    complex_names = data_service.get_all_complex_names()  #
    usd_rate = currency_service.get_current_effective_rate() or 1.0  #

    complexes_data = []
    for name in complex_names:
        if not name: continue
        # Получаем краткие KPI для отображения на плитках
        ds_data = project_dashboard_service.get_project_dashboard_data(name)  #
        if ds_data:
            kpi = ds_data.get('kpi', {})
            complexes_data.append({
                'name': name,
                'volume_usd': kpi.get('total_deals_volume', 0) / usd_rate,
                'income_usd': kpi.get('total_income', 0) / usd_rate,
                'remainders': sum(v['count'] for v in kpi.get('remainders_by_type', {}).values())
            })

    return render_template('tma/dashboard.html', complexes=complexes_data)


@tma_bp.route('/project/<complex_name>')
@tma_auth_required
def tma_project_detail(complex_name):
    """Паспорт проекта: основные метрики и статические данные."""
    data = project_dashboard_service.get_project_passport_data(complex_name)
    if not data:
        abort(404)

    # Подготовка данных для графиков (распределение по видам оплаты)
    charts = {
        'sales_stats': {
            'dates': data['dynamic_data']['payment_distribution']['labels'],
            'values': data['dynamic_data']['payment_distribution']['data']
        }
    }

    return render_template(
        'tma/project_passport.html',
        complex_name=complex_name,
        data=data['dynamic_data'],
        charts_json=json.dumps(charts)
    )


@tma_bp.route('/project/<complex_name>/plan-fact')
@tma_auth_required
def tma_plan_fact(complex_name):
    """План-фактный анализ продаж для TMA."""
    # Получение годовой динамики
    dash_data = project_dashboard_service.get_project_dashboard_data(complex_name)
    # Получение сводных данных по отклонениям и последнего месяца
    passport_data = project_dashboard_service.get_project_passport_data(complex_name)

    if not dash_data or not passport_data:
        abort(404)

    # Сериализация динамики для Plotly
    charts_json = json.dumps({
        'dynamics': dash_data['charts']['plan_fact_dynamics_yearly']
    })

    return render_template(
        'tma/plan_fact.html',
        complex_name=complex_name,
        dynamic=passport_data['dynamic_data'],
        charts_json=charts_json
    )


@tma_bp.route('/reports')
@tma_auth_required
def reports():
    """Список отчетов."""
    return render_template('tma/reports_list.html')