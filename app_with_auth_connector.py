"""Apartment Finder app with auth-connector integration.
This is the gunicorn entry point for gateway deployment."""

import os
import threading
import time
from app import create_app
from app.core.config import DevelopmentConfig
from app.core.extensions import db
from app.core.schema_repair import repair_schema
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

# Служебные команды (`flask plans check` и подобные) импортируют этот же модуль.
# Флаг ставит сам flask-cli до импорта приложения.
RUNNING_FROM_CLI = os.environ.get('FLASK_RUN_FROM_CLI') == 'true'

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


def start_background_jobs():
    """Фоновые задачи рабочего процесса: права, service discovery, прогрев тайлов.

    Отдельно от импорта модуля, потому что служебной команде всё это не нужно:
    она регистрировала в реестре второй экземпляр 'finder' и завершалась,
    оставляя там запись от уже умершего процесса.
    """
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
            init_service_discovery_flask(
                app,
                service_key="finder",
                internal_url="http://apartment-finder-app:80",
                registry_url=os.getenv('AUTH_SERVICE_URL', 'http://auth-service:80') + '/api/registry',
                heartbeat_interval=30
            )
            print("[AUTH] Service discovery initialized")
        except Exception as e:
            print(f"[AUTH] Warning: Service discovery initialization failed: {e}")

    # Warm the map tile cache in the background when TILE_SEED_ON_STARTUP is set.
    # Runs in a daemon thread and takes an inter-process lock, so only one gunicorn
    # worker does the work and the startup itself is not delayed.
    try:
        from app.web.tiles_routes import start_background_seed
        start_background_seed(app)
    except Exception as e:
        print(f"[STARTUP] Warning: tile seed not started: {e}")


def setup_database():
    """Create tables. No local users/roles — auth is gateway-only."""
    with app.app_context():
        from app.models import (auth_models, planning_models, estate_models,
                                finance_models, exclusion_models, funnel_models,
                                special_offer_models)
        db.create_all()
        print("[SETUP] Database tables created")
        # create_all() существующие таблицы не меняет, поэтому базы, созданные
        # до правок моделей, чинятся отдельно.
        repair_schema(db)


# Данные из MySQL здесь больше не «обновляются»: модели estate_*/finance_*
# читают источник напрямую через bind 'mysql_source', зеркалить их некуда.
# incremental_update_from_mysql() остался от прежней схемы с локальной копией и
# падал на первой же таблице ('EstateHouse' has no attribute 'data_hash'),
# впустую дёргая MySQL на каждом старте.
setup_database()

if not RUNNING_FROM_CLI:
    start_background_jobs()