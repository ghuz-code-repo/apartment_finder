# app/web/marketing_routes.py
"""Маркетинговый раздел портала.

Отдельный blueprint, а не вкладка в отчётах: у раздела свои пользователи
(колл-центр и маркетинг), свои права и своя навигация.
"""

from datetime import date, datetime, timedelta

from flask import Blueprint, abort, flash, render_template, request, send_file

from ..core.decorators import (current_user_can, login_required, permission_required,
                               permission_required_any)
from ..services import (best_offer_service, call_center_service, manager_link_service,
                        marketing_funnel_service)
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
@permission_required_any('marketing_call_center_view', 'marketing_call_center_view_own')
def call_center():
    """Динамика обзвона, подбора и встреч плюс разбивка по менеджерам.

    Оператор с правом «только свои» видит те же графики, но по своим заявкам:
    фильтр по менеджеру ему не показывается и подставляется принудительно —
    иначе чужие показатели уехали бы в HTML и нашлись бы поиском по странице.
    """
    start_date, end_date = _parse_period()
    granularity = request.args.get('granularity', call_center_service.DEFAULT_GRANULARITY)
    complexes = request.args.getlist('complexes')

    see_all = current_user_can('marketing_call_center_view')
    own_manager_id = None
    if see_all:
        managers = _selected_ints('managers')
    else:
        own_manager_id = manager_link_service.current_manager_id()
        if not own_manager_id:
            flash("Ваша учётная запись не сопоставлена с менеджером в CRM, "
                  "поэтому показывать нечего. Обратитесь к администратору.", "warning")
        # Ноль в фильтре — заведомо несуществующий менеджер: пустой список
        # означал бы «все», а это ровно то, чего право не разрешает.
        managers = [own_manager_id or 0]

    options = call_center_service.get_filter_options()
    options['complex_items'] = [{'value': name, 'label': name} for name in options['complexes']]
    options['manager_items'] = [{'value': m.id, 'label': m.full_name} for m in options['managers']]

    return render_template(
        'marketing/call_center.html',
        title="Колл-центр" if see_all else "Мой колл-центр",
        dynamics=call_center_service.get_dynamics(
            start_date, end_date, granularity, manager_ids=managers, complexes=complexes),
        managers=call_center_service.get_manager_stats(
            start_date, end_date, manager_ids=managers, complexes=complexes),
        options=options,
        granularities=GRANULARITIES,
        start_date=start_date,
        end_date=end_date,
        selected_complexes=complexes,
        selected_managers=managers if see_all else [],
        see_all=see_all,
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


def _parse_number(value):
    """Число из формы. Пустое и мусор -> None, фильтр просто не применяется.

    Цены вводят с пробелами-разделителями («700 000 000») — их убираем.
    Запятая считается десятичной: площадь пишут как «45,5».
    """
    if value is None or str(value).strip() == '':
        return None
    text = str(value).replace(' ', '').replace(' ', '').replace(' ', '').replace(',', '.')
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


OFFER_CURRENCIES = ('UZS', 'USD')
# Денежные фильтры: вводятся в выбранной валюте, в сервис уходят в сумах.
MONEY_FILTERS = ('price_from', 'price_to', 'price_m2_from', 'price_m2_to',
                 'monthly_from', 'monthly_to')
AREA_FILTERS = ('area_from', 'area_to')


def _usd_rate():
    """Курс UZS за 1 USD. Без курса доллары показать нельзя — вернётся None."""
    from ..services import currency_service
    try:
        rate = currency_service.get_current_effective_rate()
    except Exception:
        rate = None
    return rate if rate and rate > 0 else None


def _offer_request():
    """Разбирает параметры конструктора офера.

    Одна функция на страницу и на печать: если разбирать параметры в двух
    местах, распечатанный офер однажды окажется не тем, что на экране.
    """
    project = request.args.get('project')

    rate = _usd_rate()
    currency = request.args.get('currency', 'UZS')
    if currency not in OFFER_CURRENCIES or (currency == 'USD' and not rate):
        currency = 'UZS'
    factor = rate if currency == 'USD' else 1

    # inputs — как ввёл пользователь, в его валюте; filters — в сумах для расчёта.
    inputs = {key: _parse_number(request.args.get(key)) for key in MONEY_FILTERS + AREA_FILTERS}
    filters = {key: (value * factor if value and key in MONEY_FILTERS else value)
               for key, value in inputs.items()}

    discount_mode = request.args.get('discount_mode', 'auto')
    # Ручные проценты приходят полями вида full_payment_kd — разбираем их в
    # тот же вид, что понимает pricing_service.
    selected_discounts = {}
    for field, value in request.args.items():
        for method in ('full_payment', 'mortgage'):
            prefix = method + '_'
            if field.startswith(prefix) and value not in (None, ''):
                code = field[len(prefix):]
                try:
                    selected_discounts.setdefault(method, {})[code] = int(float(value))
                except (TypeError, ValueError):
                    continue

    manual_percents = {
        'full_payment': selected_discounts.get('full_payment', {}),
        'mortgage_standard': selected_discounts.get('mortgage', {}),
    }
    money = {'currency': currency, 'rate': rate, 'factor': factor}
    return project, filters, inputs, money, discount_mode, selected_discounts, manual_percents


def _format_amount(value, currency):
    return f'{value:,.0f}'.replace(',', ' ') + f' {currency}'


def _criteria_labels(inputs, discount_mode, currency):
    """Критерии человеческим языком — для печатной версии."""
    def bounds(low, high, fmt):
        if low and high:
            return f'{fmt(low)} — {fmt(high)}'
        return f'от {fmt(low)}' if low else f'до {fmt(high)}'

    def money(value):
        return _format_amount(value, currency)

    def area(value):
        return f'{value:g} м²'

    labels = []
    for low, high, title, fmt in (('price_from', 'price_to', 'Цена', money),
                                  ('price_m2_from', 'price_m2_to', 'Цена за м²', money),
                                  ('area_from', 'area_to', 'Площадь', area),
                                  ('monthly_from', 'monthly_to', 'Платёж по ипотеке в месяц', money)):
        if inputs.get(low) or inputs.get(high):
            labels.append(f'{title}: {bounds(inputs.get(low), inputs.get(high), fmt)}')
    labels.append('Скидки: все доступные' if discount_mode != 'manual' else 'Скидки: выбраны вручную')
    return labels


@marketing_bp.route('/best-offer')
@login_required
@permission_required('marketing_offer_view')
def best_offer():
    """Список проектов и конструктор офера по выбранному."""
    projects = best_offer_service.list_projects()
    (project, filters, inputs, money, discount_mode,
     selected_discounts, manual_percents) = _offer_request()

    if not project:
        return render_template(
            'marketing/best_offer.html',
            title="Лучший офер",
            projects=projects,
            selected_project=None,
            money=money,
        )

    offer = best_offer_service.build_offer(
        project,
        filters=filters,
        manual_percents=manual_percents,
        apply_all_discounts=discount_mode != 'manual',
    )

    return render_template(
        'marketing/best_offer.html',
        title=f"Лучший офер: {project}",
        projects=projects,
        selected_project=project,
        offer=offer,
        filters=inputs,
        money=money,
        discount_mode=discount_mode,
        selected_discounts=selected_discounts,
    )


@marketing_bp.route('/best-offer/print')
@login_required
@permission_required('marketing_offer_view')
def best_offer_print():
    """Печатная версия офера: лист A4 для печати или сохранения в PDF."""
    (project, filters, inputs, money, discount_mode,
     _selected, manual_percents) = _offer_request()
    if not project:
        abort(404)

    offer = best_offer_service.build_offer(
        project,
        filters=filters,
        manual_percents=manual_percents,
        apply_all_discounts=discount_mode != 'manual',
    )

    return render_template(
        'marketing/offer_print.html',
        offer=offer,
        money=money,
        criteria=_criteria_labels(inputs, discount_mode, money['currency']),
        current_date=datetime.now().strftime('%d.%m.%Y'),
    )


@marketing_bp.route('/lead-scoring')
@login_required
@permission_required('marketing_lead_scoring_view')
def lead_scoring():
    """Скоринг лидов в тестовом режиме: модель, её качество и проверка на свежих лидах."""
    from ..services import lead_scoring_service

    record = lead_scoring_service.active_model()
    check = None
    if record:
        try:
            check = lead_scoring_service.live_check(record)
        except Exception as e:
            # Проверка читает брони из MySQL: недоступная витрина не должна
            # прятать саму модель и её метрики.
            flash(f'Не удалось собрать проверку на свежих лидах: {e}', 'warning')

    return render_template(
        'marketing/lead_scoring.html',
        title="Скоринг лидов (тест)",
        model=record,
        check=check,
        skip_titles=_lead_skip_titles(),
    )


def _lead_skip_titles():
    from ..services.lead_scoring_features import SKIP_REASONS
    return SKIP_REASONS
