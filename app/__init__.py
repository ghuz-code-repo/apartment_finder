# app/__init__.py
import os
import json
from datetime import date, datetime
from decimal import Decimal
from flask import Flask, request, g, session, current_app, abort, has_request_context
from flask_cors import CORS
from flask_babel import Babel
from .core.config import DevelopmentConfig
from .core.extensions import db, migrate_default, migrate_planning
from .core.decorators import _is_gateway_user, permission_granted, user_permissions

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
    def short_name(self):
        """Имя в виде «Фамилия И. О.» — как подписан пользователь в шапке
        gateway. Если auth-connector прислал готовое short_name, берём его."""
        explicit = self._user.get('short_name')
        if explicit:
            return explicit
        parts = (self.full_name or '').split()
        if len(parts) >= 2:
            initials = ' '.join(p[0].upper() + '.' for p in parts[1:3])
            return f'{parts[0]} {initials}'
        return self.full_name or self.username

    @property
    def avatar_url(self):
        """URL аватара из gateway. None — шаблон покажет иконку.

        auth-connector аватар не отдаёт: в UserContext такого поля нет, и
        to_dict() его не возвращает. Поэтому берём путь прямо из заголовка
        X-User-Avatar — так же, как это делают referal и client_service.
        Путь абсолютный от корня домена, префикс /finder к нему не нужен.
        """
        explicit = self._user.get('avatar_path') or self._user.get('avatar_url')
        if explicit:
            return explicit
        if has_request_context():
            return request.headers.get('X-User-Avatar') or None
        return None

    @property
    def role(self):
        roles = self._user.get('roles', [])
        role_name = self._user.get('role', roles[0] if roles else 'user')
        return _GatewayRole(role_name)

    def can(self, perm_name):
        return permission_granted(perm_name, user_permissions(self._user))

    def get_id(self):
        return str(self.id)


def create_app(config_class=DevelopmentConfig):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    app.config['BABEL_DEFAULT_LOCALE'] = 'ru'
    # 'ru' — язык самих msgid, каталог ему не нужен. Узбекский на латинице:
    # официальная графика, её и ждут в документах для клиентов.
    app.config['LANGUAGES'] = {'en': 'English', 'ru': 'Русский', 'uz': "O'zbekcha"}

    CORS(app)
    db.init_app(app)

    migrate_default.init_app(app, db, directory='migrations_default',
                             include_symbol=lambda name, table: table.info.get('bind_key') is None)

    migrate_planning.init_app(app, db, directory='migrations_planning',
                              include_symbol=lambda name, table: table.info.get('bind_key') == 'planning_db')

    babel.init_app(app, locale_selector=select_locale)
    app.json_encoder = CustomJSONEncoder

    def fromjson_filter(value):
        return json.loads(value)

    app.jinja_env.filters['fromjson'] = fromjson_filter

    os.makedirs(app.instance_path, exist_ok=True)

    # Статика получает адрес вида ?v=<mtime файла>. Без этого браузер и шлюз
    # держат прошлую версию скриптов после деплоя, и страница работает по коду,
    # которого в шаблоне уже нет. Значения считаются один раз на процесс.
    asset_versions = {}

    @app.url_defaults
    def add_asset_version(endpoint, values):
        if endpoint != 'static' or 'filename' not in values:
            return
        filename = values['filename']
        if filename not in asset_versions:
            path = os.path.join(app.static_folder, filename)
            try:
                # Только для настоящих файлов: карта строит из url_for базовый
                # путь к папке с иконками и клеит к нему имя, а '?v=' в середине
                # такой склейки ломает адрес.
                asset_versions[filename] = int(os.stat(path).st_mtime) if os.path.isfile(path) else 0
            except OSError:
                asset_versions[filename] = 0
        if asset_versions[filename]:
            values['v'] = asset_versions[filename]

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
        from .web.tiles_routes import tiles_bp
        from .web.plans_routes import plans_bp
        from .web.media_routes import media_bp

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
        app.register_blueprint(tiles_bp)
        app.register_blueprint(plans_bp)
        app.register_blueprint(media_bp)

    @app.before_request
    def before_request_tasks():
        g.lang = str(select_locale())

    @app.context_processor
    def inject_current_user():
        """Inject gateway user as current_user for templates."""
        if hasattr(g, 'user') and g.user and _is_gateway_user(g.user):
            return {
                'current_user': GatewayUserProxy(g.user),
                'is_gateway_mode': True,
            }
        # No gateway user — not authenticated
        return {
            'current_user': None,
            'is_gateway_mode': False,
        }

    @app.route('/health')
    def health_check():
        return {'status': 'ok', 'service': 'apartment-finder'}, 200

    return app