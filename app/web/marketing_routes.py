# app/web/marketing_routes.py
"""Маркетинговый раздел портала.

Отдельный blueprint, а не вкладка в отчётах: у раздела свои пользователи
(колл-центр и маркетинг), свои права и своя навигация.
"""

from datetime import date, timedelta

from flask import Blueprint, render_template, request

from ..core.decorators import login_required, permission_required
from ..services import call_center_service
from ..services.contracting_income_service import GRANULARITIES

marketing_bp = Blueprint('marketing', __name__, template_folder='templates')

# По умолчанию — последние две недели по дням: на таком окне видно и будни,
# и выходные, а точки ещё не сливаются.
DEFAULT_RANGE_DAYS = 14


def _parse_date(value, fallback):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return fallback


def _parse_period():
    """Интервал из запроса. Перевёрнутый диапазон разворачиваем обратно."""
    today = date.today()
    start_date = _parse_date(request.args.get('start_date'),
                             today - timedelta(days=DEFAULT_RANGE_DAYS))
    end_date = _parse_date(request.args.get('end_date'), today)
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    return start_date, end_date


def _selected_ints(field):
    values = []
    for raw in request.args.getlist(field):
        try:
            values.append(int(raw))
        except (TypeError, ValueError):
            continue
    return values


@marketing_bp.route('/call-center')
@login_required
@permission_required('marketing_call_center_view')
def call_center():
    """Динамика обзвона, подбора и встреч плюс разбивка по менеджерам."""
    start_date, end_date = _parse_period()
    granularity = request.args.get('granularity', call_center_service.DEFAULT_GRANULARITY)
    complexes = request.args.getlist('complexes')
    managers = _selected_ints('managers')

    options = call_center_service.get_filter_options()
    # Шаблону нужны готовые пары значение/подпись: в Jinja нет лямбд, а фильтр
    # один и тот же для проектов и менеджеров.
    options['complex_items'] = [{'value': name, 'label': name} for name in options['complexes']]
    options['manager_items'] = [{'value': m.id, 'label': m.full_name} for m in options['managers']]

    return render_template(
        'marketing/call_center.html',
        title="Колл-центр",
        dynamics=call_center_service.get_dynamics(
            start_date, end_date, granularity, manager_ids=managers, complexes=complexes),
        managers=call_center_service.get_manager_stats(
            start_date, end_date, manager_ids=managers, complexes=complexes),
        options=options,
        granularities=GRANULARITIES,
        start_date=start_date,
        end_date=end_date,
        selected_complexes=complexes,
        selected_managers=managers,
    )
