# app/core/decorators.py
from functools import wraps
from flask import abort, request, current_app, g
from .auth_utils import verify_telegram_data

try:
    from auth_connector.auth_middleware import UserContext as _UserContext
except ImportError:
    _UserContext = None


def _is_gateway_user(user):
    """Check if user is a gateway user (dict or UserContext)."""
    if isinstance(user, dict):
        return True
    if _UserContext is not None and isinstance(user, _UserContext):
        return True
    return False

# Mapping from local permission names to gateway permission names
try:
    from permissions_setup import PERMISSION_MAP
except ImportError:
    PERMISSION_MAP = {}


def _get_current_user():
    """Get current gateway user from g.user."""
    if hasattr(g, 'user') and g.user:
        return g.user
    return None


def user_identity(user):
    """Права и признак админа одинаково для dict и UserContext.

    Формы пользователя разные: AuthMiddleware кладёт в g.user UserContext с
    полями roles/is_admin, а to_dict() и служебные вызовы — словарь, где роль
    может лежать и в 'role', и в 'roles'. Раньше каждая проверка разбирала это
    по-своему, и словарь с is_admin=True проходил в шаблоне, но получал 403 на
    самом роуте.
    """
    if isinstance(user, dict):
        permissions = user.get('permissions') or []
        roles = user.get('roles') or []
        is_admin = bool(user.get('is_admin')) or user.get('role') == 'admin'
    else:
        permissions = getattr(user, 'permissions', None) or []
        roles = getattr(user, 'roles', None) or []
        is_admin = bool(getattr(user, 'is_admin', False))
    return permissions, is_admin or 'admin' in roles


def permission_granted(permission_name, permissions):
    """Проверяет право с учётом шаблонов, как это делает auth-connector.

    Шлюз отдаёт роли как есть: если роли выдано 'finder.*', в заголовке
    X-User-Service-Permissions придёт именно строка со звёздочкой, а не
    развёрнутый список. Точное сравнение такое право не видит — пункт меню
    пропадает, а роут отвечает 403.
    """
    gateway_perm = PERMISSION_MAP.get(permission_name, permission_name)
    if gateway_perm in permissions:
        return True
    for perm in permissions:
        if perm == '*':
            return True
        # 'finder.*' покрывает 'finder.projects_info_update'
        if perm.endswith('.*') and gateway_perm.startswith(perm[:-1]):
            return True
    return False


def login_required(f):
    """Gateway-only login_required decorator."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = _get_current_user()
        if user and _is_gateway_user(user):
            return f(*args, **kwargs)
        # Not authenticated — gateway should handle this
        abort(401)
    return decorated_function


def permission_required(permission_name):
    """Gateway-only permission_required decorator."""
    def wrapper(fn):
        @wraps(fn)
        def decorated_view(*args, **kwargs):
            user = _get_current_user()
            if not user or not _is_gateway_user(user):
                abort(401)

            user_permissions, is_admin = user_identity(user)
            if is_admin:
                return fn(*args, **kwargs)
            if permission_granted(permission_name, user_permissions):
                return fn(*args, **kwargs)
            abort(403)

        return decorated_view
    return wrapper


def tma_auth_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Если включен DEBUG, разрешаем доступ для тестирования без Telegram
        if current_app.config.get('DEBUG'):
            return f(*args, **kwargs)

        # Пытаемся достать initData из заголовка или аргументов URL
        init_data = request.headers.get('X-Telegram-Init-Data') or request.args.get('init_data')

        if not init_data or not verify_telegram_data(init_data):
            current_app.logger.warning(f"TMA Auth failed for {request.path}")
            abort(401)

        return f(*args, **kwargs)

    return decorated_function