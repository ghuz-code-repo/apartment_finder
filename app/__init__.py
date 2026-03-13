# app/__init__.py
import os
import json
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy.orm import joinedload, selectinload
from flask import Flask, request, g, session, current_app, redirect
from flask_cors import CORS
from flask_babel import Babel
from .core.config import DevelopmentConfig
from .core.db_utils import get_default_session
from .core.extensions import db, migrate_default, migrate_planning, login_manager
from .core.decorators import PERMISSION_MAP, _is_gateway_user

babel = Babel()


class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        try:
            if isinstance(obj, (date, datetime)):
                return obj.isoformat()
            elif isinstance(obj, Decimal):
                return float(obj)
            iterable = iter(obj)
        except TypeError:
            pass
        else:
            return list(iterable)
        return super().default(obj)


def select_locale():
    if 'language' in session and session['language'] in current_app.config['LANGUAGES'].keys():
        return session['language']
    return request.accept_languages.best_match(current_app.config['LANGUAGES'].keys())


class _GatewayRole:
    """Mimics role object for gateway users."""
    def __init__(self, name):
        self.name = name


class GatewayUserProxy:
    """Proxy that makes gateway user dict/UserContext look like Flask-Login user for templates."""

    def __init__(self, user_data):
        if isinstance(user_data, dict):
            self._user = user_data
        else:
            # UserContext from auth-connector
            self._user = user_data.to_dict() if hasattr(user_data, 'to_dict') else {
                'id': getattr(user_data, 'user_id', 0),
                'username': getattr(user_data, 'username', 'Gateway User'),
                'full_name': getattr(user_data, 'full_name', ''),
                'roles': getattr(user_data, 'roles', []),
                'permissions': getattr(user_data, 'permissions', []),
                'is_admin': getattr(user_data, 'is_admin', False),
            }

    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        return True

    @property
    def is_anonymous(self):
        return False

    @property
    def id(self):
        return self._user.get('id') or self._user.get('user_id', 0)

    @property
    def username(self):
        return self._user.get('username', 'Gateway User')

    @property
    def full_name(self):
        return self._user.get('full_name', self.username)

    @property
    def role(self):
        roles = self._user.get('roles', [])
        role_name = self._user.get('role', roles[0] if roles else 'user')
        return _GatewayRole(role_name)

    @property
    def is_admin(self):
        if self._user.get('is_admin'):
            return True
        roles = self._user.get('roles', [])
        return 'admin' in roles

    def can(self, perm_name):
        if self.is_admin:
            return True
        gateway_perm = PERMISSION_MAP.get(perm_name, perm_name)
        return gateway_perm in self._user.get('permissions', [])

    def get_id(self):
        return str(self.id)


def create_app(config_class=DevelopmentConfig):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    app.config['BABEL_DEFAULT_LOCALE'] = 'ru'
    app.config['LANGUAGES'] = {'en': 'English', 'ru': 'Русский'}

    CORS(app)
    db.init_app(app)

    migrate_default.init_app(app, db, directory='migrations_default',
                             include_symbol=lambda name, table: table.info.get('bind_key') is None)

    migrate_planning.init_app(app, db, directory='migrations_planning',
                              include_symbol=lambda name, table: table.info.get('bind_key') == 'planning_db')

    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = "Пожалуйста, войдите в систему для доступа к этой странице."
    login_manager.login_message_category = "info"

    babel.init_app(app, locale_selector=select_locale)
    app.json_encoder = CustomJSONEncoder

    def fromjson_filter(value):
        return json.loads(value)

    app.jinja_env.filters['fromjson'] = fromjson_filter

    os.makedirs(app.instance_path, exist_ok=True)

    with app.app_context():
        # Импорт моделей
        from .models import auth_models, planning_models, estate_models, finance_models, exclusion_models, \
            funnel_models, special_offer_models, registry_models

        # Локальный импорт Blueprints для предотвращения циклической зависимости
        from .web.main_routes import main_bp
        from .web.auth_routes import auth_bp
        from .web.discount_routes import discount_bp
        from .web.report_routes import report_bp
        from .web.complex_calc_routes import complex_calc_bp
        from .web.settings_routes import settings_bp
        from .web.api_routes import api_bp
        from .web.special_offer_routes import special_offer_bp
        from .web.manager_analytics_routes import manager_analytics_bp
        from .web.obligations_routes import obligations_bp
        from .web.competitor_routes import competitor_bp
        from .web.registry_routes import registry_bp
        from .web.cancellation_routes import cancellation_bp
        from .web.news_routes import news_bp
        from .web.ai_routes import ai_bp
        from .web.tma_routes import tma_bp
        from .web.sync_routes import sync_bp

        # Регистрация Blueprints
        app.register_blueprint(report_bp, url_prefix='/reports')
        app.register_blueprint(main_bp)
        app.register_blueprint(auth_bp)
        app.register_blueprint(discount_bp)
        app.register_blueprint(complex_calc_bp)
        app.register_blueprint(settings_bp)
        app.register_blueprint(api_bp, url_prefix='/api/v1')
        app.register_blueprint(special_offer_bp, url_prefix='/specials')
        app.register_blueprint(manager_analytics_bp, url_prefix='/manager-analytics')
        app.register_blueprint(obligations_bp)
        app.register_blueprint(competitor_bp)
        app.register_blueprint(registry_bp)
        app.register_blueprint(cancellation_bp)
        app.register_blueprint(news_bp)
        app.register_blueprint(ai_bp)
        app.register_blueprint(tma_bp, url_prefix='/tma')
        app.register_blueprint(sync_bp, url_prefix='/api/sync')

        @login_manager.user_loader
        def load_user(user_id):
            default_session = get_default_session()
            return default_session.query(auth_models.User).options(
                joinedload(auth_models.User.role).selectinload(auth_models.Role.permissions)
            ).get(int(user_id))

    @app.before_request
    def before_request_tasks():
        g.lang = str(select_locale())

    @app.context_processor
    def inject_current_user():
        """Make current_user work in both gateway and local modes."""
        from flask_login import current_user as flask_login_user

        is_gateway = False

        # Gateway mode: g.user is set by auth middleware
        if hasattr(g, 'user') and g.user and _is_gateway_user(g.user):
            is_gateway = True
            return {
                'current_user': GatewayUserProxy(g.user),
                'is_gateway_mode': True,
            }

        # Local mode: use Flask-Login
        return {
            'current_user': flask_login_user,
            'is_gateway_mode': is_gateway,
        }

    @login_manager.unauthorized_handler
    def unauthorized():
        """Handle unauthorized access."""
        # If behind gateway, return 401 (gateway handles redirect)
        if hasattr(g, 'user'):
            from flask import abort
            abort(401)
        # Local mode: redirect to login
        return redirect('/login')

    @app.route('/health')
    def health_check():
        return {'status': 'ok', 'service': 'apartment-finder'}, 200

    return app