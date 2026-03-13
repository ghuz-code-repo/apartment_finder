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
            permissions_map = {
                'view_selection': 'Просмотр системы подбора',
                'view_discounts': 'Просмотр активной системы скидок',
                'view_version_history': 'Просмотр истории версий скидок',
                'view_plan_fact_report': 'Просмотр План-факт отчета',
                'view_inventory_report': 'Просмотр отчета по остаткам',
                'view_manager_report': 'Просмотр отчетов по менеджерам',
                'view_project_dashboard': 'Просмотр аналитики по проектам',
                'manage_discounts': 'Управление версиями скидок',
                'manage_settings': 'Управление настройками',
                'manage_users': 'Управление пользователями',
                'upload_data': 'Загрузка данных',
                'download_kpi_report': 'Выгрузка ведомости по KPI менеджеров',
                'manage_specials': 'Управление специальными предложениями'
            }
            roles_permissions = {
                'MPP': ['view_selection', 'view_discounts'],
                'MANAGER': [
                    'view_selection', 'view_discounts', 'view_version_history', 'manage_settings',
                    'view_plan_fact_report', 'view_inventory_report', 'view_manager_report', 'view_project_dashboard'
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
