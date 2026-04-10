"""Apartment Finder app with auth-connector integration.
This is the gunicorn entry point for gateway deployment."""

import os
import threading
import time
from app import create_app
from app.core.config import DevelopmentConfig
from app.services.initial_load_service import incremental_update_from_mysql
from app.core.extensions import db
from app.models import auth_models
from werkzeug.middleware.proxy_fix import ProxyFix
from prefix_middleware import PrefixMiddleware

# AUTH-CONNECTOR INTEGRATION
try:
    from auth_connector import AuthMiddleware, AuthClient, init_service_discovery_flask
    from permissions_setup import permissions_registry
except ImportError:
    print("Warning: auth-connector not installed. Install with: pip install -e ../auth-connector")
    AuthMiddleware = None
    AuthClient = None
    init_service_discovery_flask = None
    permissions_registry = None

# Create Flask app
app = create_app(DevelopmentConfig)

# Configure proxy fix for running behind nginx gateway
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.wsgi_app = PrefixMiddleware(app.wsgi_app, app=app, prefix='/finder')

# AUTH-CONNECTOR MIDDLEWARE
if AuthMiddleware:
    jwt_secret = os.getenv('JWT_SECRET')
    if jwt_secret:
        auth_middleware = AuthMiddleware(app, jwt_secret=jwt_secret)
        print("[AUTH] Auth middleware initialized with JWT validation")
    else:
        print("[AUTH] WARNING: JWT_SECRET not set, auth middleware disabled")

# Sync permissions with gateway (delayed to allow gunicorn to start serving first)
if AuthClient and permissions_registry:
    auth_service_url = os.getenv('AUTH_SERVICE_URL', 'http://auth-service:80')
    internal_api_key = os.getenv('INTERNAL_API_KEY', '')
    if internal_api_key:
        def _sync_permissions_delayed():
            """Wait for gunicorn to be ready, then trigger permission sync."""
            time.sleep(5)
            auth_client = AuthClient(auth_service_url, service_key="finder", api_key=internal_api_key)
            with app.app_context():
                try:
                    permissions_data = permissions_registry.to_dict()['permissions']
                    auth_client.sync_permissions(permissions_data)
                    print(f"[AUTH] Synced {len(permissions_data)} permissions with gateway")
                except Exception as e:
                    print(f"[AUTH] Warning: Could not sync permissions: {e}")

        _sync_thread = threading.Thread(target=_sync_permissions_delayed, daemon=True)
        _sync_thread.start()

# Service discovery registration
if init_service_discovery_flask:
    try:
        auth_service_url = os.getenv('AUTH_SERVICE_URL', 'http://auth-service:80')
        service_discovery_client = init_service_discovery_flask(
            app,
            service_key="finder",
            internal_url="http://apartment-finder-app:80",
            registry_url=auth_service_url + '/api/registry',
            heartbeat_interval=30
        )
        print("[AUTH] Service discovery initialized")
    except Exception as e:
        print(f"[AUTH] Warning: Service discovery initialization failed: {e}")


def setup_database():
    """Create tables and initial admin user."""
    with app.app_context():
        from app.models import (auth_models, planning_models, estate_models,
                                finance_models, exclusion_models, funnel_models,
                                special_offer_models)
        db.create_all()

        if auth_models.Role.query.count() == 0:
            from permissions_setup import PERMISSION_MAP
            # Build permissions from the central registry
            permissions_map = {
                # Selection
                'selection_view': 'Подбор: просмотр',
                'selection_details_view': 'Подбор: карточка объекта',
                'selection_commercial_offer_view': 'Подбор: КП',
                'selection_specials_view': 'Подбор: спецпредложения',
                # Discounts
                'discounts_view': 'Скидки: просмотр',
                'discounts_versions_view': 'Скидки: история версий',
                'discounts_versions_create': 'Скидки: создание черновика',
                'discounts_versions_update': 'Скидки: редактирование',
                'discounts_versions_delete': 'Скидки: удаление версии',
                'discounts_comment_create': 'Скидки: комментарии',
                'discounts_import': 'Скидки: загрузка',
                'discounts_template_export': 'Скидки: шаблон',
                # Reports
                'reports_plan_fact_view': 'Отчеты: план-факт',
                'reports_plan_fact_export': 'Отчеты: экспорт план-факт',
                'reports_annual_plan_fact_export': 'Отчеты: годовой план-факт',
                'reports_sales_funnel_view': 'Отчеты: воронка продаж',
                'reports_funnel_leads_view': 'Отчеты: лиды воронки',
                'reports_financial_model_view': 'Отчеты: фин. модель',
                'reports_inventory_view': 'Отчеты: остатки',
                'reports_inventory_export': 'Отчеты: экспорт остатков',
                'reports_commercial_inventory_export': 'Отчеты: экспорт коммерции',
                'reports_deal_registry_view': 'Отчеты: реестр сделок',
                'reports_deal_registry_export': 'Отчеты: экспорт реестра',
                'reports_quarterly_view': 'Отчеты: квартальная',
                'reports_refund_view': 'Отчеты: возвраты',
                'reports_sales_pace_view': 'Отчеты: темпы продаж',
                'reports_expected_income_export': 'Отчеты: экспорт ожид. дохода',
                'reports_plan_import': 'Отчеты: загрузка плана',
                'reports_plan_template_export': 'Отчеты: шаблон плана',
                # Managers
                'managers_performance_view': 'Менеджеры: планы',
                'managers_performance_detail_view': 'Менеджеры: детали плана',
                'managers_kpi_calculate': 'Менеджеры: расчет KPI',
                'managers_kpi_export': 'Менеджеры: выгрузка KPI',
                'managers_analytics_view': 'Менеджеры: аналитика',
                'managers_yearly_view': 'Менеджеры: годовой отчет',
                'managers_leads_view': 'Менеджеры: лиды',
                'managers_plan_import': 'Менеджеры: загрузка плана',
                'managers_plan_template_export': 'Менеджеры: шаблон плана',
                'managers_hall_of_fame_view': 'Менеджеры: доска почета',
                'managers_obligations_view': 'Менеджеры: обязательства',
                # Projects
                'projects_dashboard_view': 'Проекты: дашборд',
                'projects_passport_view': 'Проекты: паспорт',
                'projects_passport_update': 'Проекты: ред. паспорта',
                'projects_pricelist_export': 'Проекты: прайс-лист',
                'projects_passport_export': 'Проекты: экспорт паспорта',
                'projects_competitor_import': 'Проекты: загрузка конкурентов',
                'projects_competitor_template_export': 'Проекты: шаблон конкурентов',
                # Competitors
                'competitors_map_view': 'Конкуренты: карта',
                'competitors_profile_view': 'Конкуренты: профиль',
                'competitors_profile_update': 'Конкуренты: ред. профиля',
                'competitors_compare_view': 'Конкуренты: сравнение',
                'competitors_dynamics_view': 'Конкуренты: динамика',
                'competitors_media_upload': 'Конкуренты: загрузка медиа',
                'competitors_media_delete': 'Конкуренты: удаление медиа',
                'competitors_our_export': 'Конкуренты: экспорт наших',
                'competitors_our_import': 'Конкуренты: импорт наших',
                'competitors_external_export': 'Конкуренты: экспорт внешних',
                'competitors_external_import': 'Конкуренты: импорт внешних',
                'competitors_import_view': 'Конкуренты: страница импорта',
                # Specials
                'specials_view': 'Спецпредложения: просмотр',
                'specials_create': 'Спецпредложения: создание',
                'specials_update': 'Спецпредложения: редактирование',
                'specials_delete': 'Спецпредложения: удаление',
                # Settings
                'settings_calculator_view': 'Настройки: калькуляторы',
                'settings_currency_view': 'Настройки: курс валют',
                'settings_exclusions_view': 'Настройки: исключения',
                'settings_inventory_exclusions_view': 'Настройки: искл. остатков',
                'settings_email_view': 'Настройки: email рассылка',
                'settings_routes_view': 'Настройки: маршруты',
                'settings_zero_mortgage_template': 'Настройки: шаблон 0% ипотеки',
                # Users
                'users_view': 'Пользователи: просмотр',
                'users_create': 'Пользователи: создание',
                'users_delete': 'Пользователи: удаление',
                'roles_view': 'Роли: просмотр',
                'roles_create': 'Роли: создание',
                'roles_update': 'Роли: редактирование',
                'roles_delete': 'Роли: удаление',
                # Registry
                'registry_view': 'Реестр: просмотр',
                'registry_create': 'Реестр: добавление',
                'registry_delete': 'Реестр: удаление',
                # Cancellations
                'cancellations_view': 'Расторжения: просмотр',
                'cancellations_create': 'Расторжения: добавление',
                'cancellations_update': 'Расторжения: редактирование',
                'cancellations_delete': 'Расторжения: удаление',
                'cancellations_export': 'Расторжения: экспорт',
                # News
                'news_view': 'Новости: просмотр',
                'news_create': 'Новости: добавление',
                'news_delete': 'Новости: удаление',
                # AI
                'ai_forecast_view': 'AI: прогнозы',
                'ai_train': 'AI: обучение',
                'ai_predict': 'AI: предсказание',
                # Complex Calc
                'complex_calc_view': 'Калькулятор: просмотр',
                'complex_calc_calculate': 'Калькулятор: расчет',
                'complex_calc_print': 'Калькулятор: печать КП',
            }
            roles_permissions = {
                'MPP': ['selection_view', 'selection_details_view', 'discounts_view', 'complex_calc_view', 'complex_calc_calculate'],
                'MANAGER': [
                    'selection_view', 'selection_details_view', 'selection_commercial_offer_view', 'selection_specials_view',
                    'discounts_view', 'discounts_versions_view',
                    'reports_plan_fact_view', 'reports_sales_funnel_view', 'reports_financial_model_view',
                    'reports_inventory_view', 'reports_deal_registry_view', 'reports_quarterly_view',
                    'reports_refund_view', 'reports_sales_pace_view',
                    'managers_performance_view', 'managers_analytics_view', 'managers_obligations_view',
                    'projects_dashboard_view', 'projects_passport_view',
                    'competitors_map_view', 'competitors_profile_view', 'competitors_compare_view', 'competitors_dynamics_view',
                    'news_view',
                    'complex_calc_view', 'complex_calc_calculate', 'complex_calc_print',
                    'settings_calculator_view',
                ],
                'ADMIN': list(permissions_map.keys())
            }
            all_permissions = {}
            for name, desc in permissions_map.items():
                p = auth_models.Permission(name=name, description=desc)
                all_permissions[name] = p
                db.session.add(p)
            for role_name, permissions_list in roles_permissions.items():
                role = auth_models.Role(name=role_name)
                db.session.add(role)
                for p_name in permissions_list:
                    if p_name in all_permissions:
                        role.permissions.append(all_permissions[p_name])
            db.session.commit()
            print("[SETUP] Roles and permissions created")

        if auth_models.User.query.filter_by(username='admin').first() is None:
            admin_role = auth_models.Role.query.filter_by(name='ADMIN').first()
            if admin_role:
                admin_user = auth_models.User(
                    username='admin',
                    role=admin_role,
                    full_name='Администратор Системы',
                    email='d.plakhotnyi@gh.uz'
                )
                admin_user.set_password(os.getenv('ADMIN_PASSWORD', 'ChangeMe!2024'))
                db.session.add(admin_user)
                db.session.commit()
                print("[SETUP] Admin user created")


# Run setup and data update on startup
setup_database()
try:
    with app.app_context():
        incremental_update_from_mysql()
except Exception as e:
    print(f"[STARTUP] Warning: MySQL update failed: {e}")
