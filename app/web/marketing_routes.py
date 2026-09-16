# app/web/marketing_routes.py
"""Маркетинговый раздел портала.

Отдельный blueprint, а не вкладка в отчётах: у раздела свои пользователи
(колл-центр и маркетинг), свои права и своя навигация.
"""

from datetime import date, timedelta

from flask import Blueprint, abort, render_template, request, send_file

from ..core.decorators import login_required, permission_required
from ..services import call_center_service, marketing_funnel_service
from ..services.contracting_income_service import GRANULARITIES

marketing_bp = Blueprint('marketing', __name__, template_folder='templates')

# По умолчанию — последние две недели по дням: на таком окне видно и будни,
# и выходные, а точки ещё не сливаются.
DEFAULT_RANGE_DAYS = 14

# Сколько контактов показываем на экране. Выгрузка отдаёт всех: таблица на
# несколько тысяч строк только мешает, а файл открывают в Excel.
CONTACTS_PAGE_LIMIT = 200


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


def _funnel_params():
    """Общие параметры воронки для страницы и выгрузки."""
    start_date, end_date = _parse_period()
    # Фильтры одиночные: маркетолог смотрит один проект и один канал, а
    # мультивыбор здесь только усложнил бы ссылку на этап.
    complexes = [value for value in [request.args.get('complexes')] if value]
    channels = [value for value in [request.args.get('channels')] if value]
    return start_date, end_date, complexes, channels


@marketing_bp.route('/funnel')
@login_required
@permission_required('marketing_funnel_view')
def funnel():
    """Этапы воронки и контакты выбранного этапа."""
    start_date, end_date, complexes, channels = _funnel_params()
    stage_key = request.args.get('stage')

    data = marketing_funnel_service.get_funnel(start_date, end_date, complexes, channels)

    contacts = []
    stage_count = 0
    if stage_key:
        stage_count = next((s['count'] for s in data['stages'] if s['key'] == stage_key), 0)
        contacts = marketing_funnel_service.get_stage_contacts(
            stage_key, start_date, end_date, complexes, channels,
            limit=CONTACTS_PAGE_LIMIT)

    stage = marketing_funnel_service.STAGE_BY_KEY.get(stage_key)
    return render_template(
        'marketing/funnel.html',
        title="Воронка",
        funnel=data,
        options=marketing_funnel_service.get_filter_options(),
        start_date=start_date,
        end_date=end_date,
        selected_complexes=complexes,
        selected_channels=channels,
        selected_stage=stage_key if stage else None,
        stage_title=stage['title'] if stage else None,
        stage_count=stage_count,
        contacts=contacts,
        contacts_truncated=stage_count > len(contacts),
    )


@marketing_bp.route('/funnel/export')
@login_required
@permission_required('marketing_funnel_export')
def funnel_export():
    """Выгрузка контактов этапа в Excel."""
    start_date, end_date, complexes, channels = _funnel_params()
    stage_key = request.args.get('stage')
    stage = marketing_funnel_service.STAGE_BY_KEY.get(stage_key)
    if not stage:
        abort(404)

    rows = marketing_funnel_service.get_stage_contacts(
        stage_key, start_date, end_date, complexes, channels)
    stream = marketing_funnel_service.export_contacts_excel(rows, stage['title'])

    filename = f"contacts_{stage_key}_{start_date.isoformat()}_{end_date.isoformat()}.xlsx"
    return send_file(
        stream,
        download_name=filename,
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
