# app/web/main_routes.py

from datetime import datetime
from urllib.parse import urlparse

from flask import session
from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from flask import abort
from flask import g
from flask_babel import gettext as _
from ..core.decorators import permission_required, login_required
from app.services import special_offer_service
from ..core.db_utils import get_default_session, get_mysql_session
from ..models.estate_models import EstateHouse
from ..models.exclusion_models import ExcludedSell
# --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
from ..services import currency_service, flat_plan_service, pricing_service, project_info_service
# Импортируем PropertyType и PaymentMethod из их нового местоположения
from ..models.planning_models import PropertyType, PaymentMethod
from ..services import settings_service
from ..services.data_service import get_sells_with_house_info, get_filter_options

from ..services.selection_service import find_apartments_by_budget, get_apartment_card_data

main_bp = Blueprint('main', __name__, template_folder='templates')

@main_bp.route('/language/<lang>')
def set_language(lang=None):
    # Языков стало три, и значение приходит из URL: незнакомый код молча
    # переводил интерфейс в фолбэк, а referrer с чужого хоста превратил бы
    # переключатель в открытый редирект.
    if lang not in current_app.config['LANGUAGES']:
        abort(404)
    session['language'] = lang

    target = request.referrer or ''
    if urlparse(target).netloc not in ('', urlparse(request.host_url).netloc):
        target = ''
    return redirect(target or url_for('main.index'))

@main_bp.route('/show-all-routes')
@login_required
@permission_required('settings_routes_view')
def show_all_routes():
    """Временная страница для отображения всех зарегистрированных маршрутов."""
    rules = []
    for rule in current_app.url_map.iter_rules():
        rules.append(f"Endpoint: {rule.endpoint}, Path: {rule.rule}, Methods: {','.join(rule.methods)}")

    rules.sort()

    response_html = "<h1>Зарегистрированные URL-адреса</h1><ul>"
    for r in rules:
        # Выделим жирным маршруты нашего проблемного модуля
        if 'special_offer' in r:
            response_html += f"<li><strong>{r}</strong></li>"
        else:
            response_html += f"<li>{r}</li>"
    response_html += "</ul>"

    return response_html

@main_bp.route('/search-by-id', methods=['POST'])
@login_required
@permission_required('selection_view')
def search_by_id():
    sell_id = request.form.get('search_id')
    if sell_id:
        try:
            int(sell_id)
            return redirect(url_for('main.apartment_details', sell_id=sell_id))
        except ValueError:
            flash('Пожалуйста, введите корректный числовой ID.', 'warning')
            return redirect(url_for('main.selection'))
    else:
        flash('Вы не ввели ID для поиска.', 'info')
        return redirect(url_for('main.selection'))


@main_bp.route('/')
@login_required
def index():
    """Redirect to first available page based on user permissions."""
    from app import GatewayUserProxy
    # Gateway-only: get user from g.user, wrap in proxy for .can()
    raw_user = getattr(g, 'user', None)
    if not raw_user:
        abort(401)
    user = GatewayUserProxy(raw_user)

    # Admin — сразу на подбор
    if hasattr(user, 'is_admin') and user.is_admin:
        return redirect(url_for('main.selection'))

    # Ordered list: (permission, endpoint). First match wins.
    pages = [
        ('selection_view', 'main.selection'),
        ('discounts_view', 'discount.discounts_overview'),
        ('reports_plan_fact_view', 'report.plan_fact_report'),
        ('reports_inventory_view', 'report.inventory_summary'),
        ('managers_analytics_view', 'manager_analytics.show_report'),
        ('managers_performance_view', 'report.manager_performance_report'),
        ('competitors_map_view', 'competitor.map_view'),
        ('ai_forecast_view', 'ai.forecast_page'),
        ('registry_view', 'registry.index'),
        ('cancellations_view', 'cancellations.index'),
        ('news_view', 'news.feed'),
        ('settings_calculator_view', 'settings.manage_settings'),
    ]

    for perm, endpoint in pages:
        if user.can(perm):
            return redirect(url_for(endpoint))

    # No matching permissions — 403
    abort(403)


@main_bp.route('/home')
@login_required
@permission_required('selection_view')
def home():
    """Original index page with apartment list."""
    page = request.args.get('page', 1, type=int)
    PER_PAGE = 40
    sells_pagination = get_sells_with_house_info(page=page, per_page=PER_PAGE)

    if not sells_pagination:
        flash("Не удалось загрузить данные о продажах.", "danger")
        return render_template('main/index.html', title='Ошибка', sells_pagination=None)

    return render_template('main/index.html', title='Главная', sells_pagination=sells_pagination)


@main_bp.route('/selection', methods=['GET', 'POST'])
@login_required
@permission_required('selection_view')
def selection():
    results = None
    filter_options = get_filter_options()

    # --- НАЧАЛО ИЗМЕНЕНИЙ ---

    # Создаем переведенные списки для передачи в шаблон
    translated_property_types = [
        {'value': pt.value, 'display': _(pt.value)} for pt in PropertyType
    ]
    translated_payment_methods = [
        # Экранируем '%' для gettext
        {'value': pm.value, 'display': _(pm.value.replace('%', '%%'))} for pm in PaymentMethod
    ]

    if request.method == 'POST':
        try:
            budget = float(request.form.get('budget'))
            currency = request.form.get('currency')
            prop_type_str = request.form.get('property_type')
            floor = request.form.get('floor')
            rooms = request.form.get('rooms')
            payment_method = request.form.get('payment_method')

            results = find_apartments_by_budget(
                budget,
                currency,
                prop_type_str,
                floor=floor,
                rooms=rooms,
                payment_method=payment_method
            )
        except (ValueError, TypeError):
            flash("Пожалуйста, введите корректную сумму бюджета.", "danger")

    return render_template('main/selection.html',
                           title=_("Подбор по бюджету"),  # <-- Тоже переводим заголовок
                           results=results,
                           # --- НАЧАЛО ИЗМЕНЕНИЙ: Передаем новые списки в шаблон ---
                           property_types=translated_property_types,
                           payment_methods=translated_payment_methods,
                           # --- КОНЕЦ ИЗМЕНЕНИЙ ---
                           filter_options=filter_options)


@main_bp.route('/apartment/<int:sell_id>')
@login_required
@permission_required('selection_details_view')
def apartment_details(sell_id):
    card_data = get_apartment_card_data(sell_id)
    # Лимиты доп. скидок уже лежат внутри каждого варианта оплаты — отдельный
    # список матрицы шаблону больше не нужен.
    card_data.pop('all_discounts_for_property_type', None)

    return render_template(
        'main/apartment_details.html',
        data=card_data,
        flat_plans=flat_plan_service.get_flat_plans(sell_id),
        title=f"Детали объекта ID {sell_id}"
    )


@main_bp.route('/commercial-offer/<int:sell_id>')
@login_required
@permission_required('selection_commercial_offer_view')
def generate_commercial_offer(sell_id):
    card_data = get_apartment_card_data(sell_id)
    if not card_data.get('apartment'):
        return "Apartment not found", 404

    # Скидки, выставленные менеджером на карточке. Пересчёт идёт той же функцией,
    # что и на странице объекта, поэтому цифры в КП совпадают с экраном.
    user_selections = pricing_service.parse_manual_selections(request.args.get('selections'))
    for option in card_data.get('pricing', []):
        pricing_service.recalculate(option, user_selections.get(option['type_key'], {}))

    # Ежемесячный взнос по ипотеке считается от тела кредита, поэтому условия
    # банка проставляются после пересчёта скидок.
    calc_settings = settings_service.get_calculator_settings()
    pricing_service.apply_mortgage_terms(
        card_data.get('pricing', []),
        calc_settings.mortgage_rate_annual,
        calc_settings.mortgage_term_months
    )

    # Первая страница КП — о проекте: рендер, тексты и УТП из карточки ЖК,
    # плюс УТП самой квартиры, если на неё заведено спецпредложение.
    house = card_data.get('apartment', {}).get('house') or {}
    project_info = project_info_service.get_project_info(house.get('complex_name')) if house.get('complex_name') else None
    project_renders = project_info_service.get_renders(house['complex_name']) if project_info else []
    special = special_offer_service.get_special_offer_details_by_sell_id(sell_id)
    apartment_usp = (special or {}).get('usp_text')

    current_date = datetime.now().strftime("%d.%m.%Y %H:%M")
    usd_rate_from_cbu = currency_service.get_current_effective_rate()
    fallback_usd_rate = current_app.config.get('USD_TO_UZS_RATE', 12650.0)
    actual_usd_rate = usd_rate_from_cbu if usd_rate_from_cbu is not None else fallback_usd_rate

    return render_template(
        'main/commercial_offer.html',
        data=card_data,
        flat_plans=flat_plan_service.get_flat_plans(sell_id),
        project_info=project_info,
        project_render_url=(project_info_service.get_render_url(project_renders[0].filename)
                            if project_renders else None),
        apartment_usp=apartment_usp,
        current_date=current_date,
        usd_to_uzs_rate=actual_usd_rate,
        title=f"КП по объекту ID {sell_id}"
    )


@main_bp.route('/exclusions', methods=['GET', 'POST'])
@login_required
@permission_required('settings_exclusions_view')
def manage_exclusions():
    default_session = get_default_session()  # <--- ДОБАВЛЕНО
    mysql_session = get_mysql_session()
    if request.method == 'POST':
        if 'sell_id_to_manage' in request.form:
            action = request.form.get('action')
            sell_id_str = request.form.get('sell_id_to_manage')
            comment = request.form.get('comment', '').strip()

            if not sell_id_str:
                flash("ID квартиры не может быть пустым.", "danger")
            else:
                try:
                    sell_id = int(sell_id_str)
                    if action == 'add':
                        if default_session.query(ExcludedSell).filter_by(sell_id=sell_id).first():
                            flash(f"Квартира с ID {sell_id} уже в исключениях.", "warning")
                        else:
                            default_session.add(ExcludedSell(sell_id=sell_id, comment=comment or None))  # <--- ИЗМЕНЕНО
                            default_session.commit()
                            flash(f"Квартира ID {sell_id} добавлена в исключения.", "success")
                    elif action == 'delete':
                        exclusion = default_session.query(ExcludedSell).filter_by(sell_id=sell_id).first()
                        if exclusion:
                            default_session.delete(exclusion)  # <--- ИЗМЕНЕНО
                            default_session.commit()
                            flash(f"Квартира ID {sell_id} удалена из исключений.", "success")
                except ValueError:
                    flash("ID квартиры должен быть числом.", "danger")

        elif 'complex_name_to_toggle' in request.form:
            complex_name = request.form.get('complex_name_to_toggle')
            if complex_name:
                message, category = settings_service.toggle_complex_exclusion(complex_name)
                flash(message, category)

        return redirect(url_for('main.manage_exclusions'))

    excluded_sells = default_session.query(ExcludedSell).order_by(ExcludedSell.created_at.desc()).all()  # <--- ИЗМЕНЕНО
    all_complexes = mysql_session.query(EstateHouse.complex_name).distinct().order_by(
        EstateHouse.complex_name).all()  # <--- ИЗМЕНЕНО
    excluded_complexes_names = {c.complex_name for c in settings_service.get_all_excluded_complexes()}

    return render_template(
        'settings/manage_exclusions.html',
        title="Управление исключениями",
        excluded_sells=excluded_sells,
        all_complexes=[c[0] for c in all_complexes],
        excluded_complex_names=excluded_complexes_names
    )


@main_bp.route('/monthly-specials')
@login_required
@permission_required('selection_specials_view')
def monthly_specials_list():
    """Отображает галерею активных квартир месяца."""
    active_offers = special_offer_service.get_active_special_offers()
    return render_template('special_offers/monthly_specials_list.html',
                           title="Квартиры месяца",
                           offers=active_offers)


@main_bp.route('/special-offer/<int:sell_id>')
@login_required
@permission_required('selection_specials_view')
def special_offer_detail(sell_id):
    """Отображает детальную страницу спец. предложения."""
    offer_details = special_offer_service.get_special_offer_details_by_sell_id(sell_id)
    if not offer_details:
        abort(404)

    # Дополнительно получаем стандартную карточку квартиры для полной информации
    full_card_data = get_apartment_card_data(sell_id)

    return render_template('special_offers/special_offer_detail.html',
                           title=f"Спецпредложение: Квартира {sell_id}",
                           offer=offer_details,
                           card_data=full_card_data)



@main_bp.route('/fix-permissions')
@login_required
def fix_permissions():
    """Deprecated: permissions are now managed by the gateway."""
    abort(404)