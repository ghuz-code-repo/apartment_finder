# app/core/decorators.py
from functools import wraps
from flask import abort, request, current_app, g, redirect, url_for
from flask_login import current_user as flask_login_current_user
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
# Import from central permissions_setup to keep single source of truth
try:
    from permissions_setup import PERMISSION_MAP
except ImportError:
    # Fallback: inline map for when permissions_setup is unavailable
    PERMISSION_MAP = {}


def _get_current_user():
    """Get current user from gateway (g.user) or Flask-Login fallback."""
    if hasattr(g, 'user') and g.user:
        return g.user
    return flask_login_current_user


def login_required(f):
    """Gateway-aware login_required decorator."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = _get_current_user()
        # Gateway user (dict or UserContext from auth middleware)
        if _is_gateway_user(user):
            return f(*args, **kwargs)
        # Flask-Login user
        if hasattr(user, 'is_authenticated') and user.is_authenticated:
            return f(*args, **kwargs)
        # Not authenticated
        if hasattr(g, 'user') and g.user is None:
            # Behind gateway but not authenticated — should not happen normally
            abort(401)
        return redirect(url_for('auth.login', next=request.url))
    return decorated_function


def permission_required(permission_name):
    """Gateway-aware permission_required decorator."""
    def wrapper(fn):
        @wraps(fn)
        def decorated_view(*args, **kwargs):
            user = _get_current_user()

            # Gateway user (dict or UserContext with permissions)
            if _is_gateway_user(user):
                gateway_perm = PERMISSION_MAP.get(permission_name, permission_name)
                if isinstance(user, dict):
                    user_permissions = user.get('permissions', [])
                    user_role = user.get('role', '')
                    is_admin = user_role == 'admin'
                else:
                    # UserContext from auth-connector
                    user_permissions = user.permissions
                    is_admin = user.is_admin or 'admin' in user.roles
                if is_admin:
                    return fn(*args, **kwargs)
                if gateway_perm in user_permissions:
                    return fn(*args, **kwargs)
                abort(403)

            # Flask-Login fallback
            if not hasattr(user, 'is_authenticated') or not user.is_authenticated:
                return redirect(url_for('auth.login', next=request.url))
            if not user.can(permission_name):
                abort(403)
            return fn(*args, **kwargs)

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