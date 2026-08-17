# app/core/decorators.py
from functools import wraps
from flask import abort, request, current_app, g
from .auth_utils import verify_telegram_data

try:
    from auth_connector.auth_middleware import UserContext as _UserContext
except ImportError:
    _UserContext = None

try:
    from auth_connector.permission_utils import (any_permission_granted as _any_granted,
                                                 extract_permissions as _extract_permissions,
                                                 permission_granted as _granted)
except ImportError:
    # Локальный запуск без установленного auth-connector: те же правила,
    # чтобы поведение проверок не расходилось с продом.
    def _granted(permission_name, permissions):
        if not permission_name:
            return False
        for perm in permissions or ():
            if perm == permission_name or perm == '*':
                return True
            if perm.endswith('.*') and permission_name.startswith(perm[:-1]):
                return True
        return False

    def _any_granted(permission_names, permissions):
        permissions = list(permissions or ())
        return any(_granted(name, permissions) for name in permission_names)

    def _extract_permissions(user):
        if user is None:
            return []
        if isinstance(user, dict):
            return list(user.get('permissions') or ())
        return list(getattr(user, 'permissions', None) or ())


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


def user_permissions(user):
    """Права пользователя одинаково для dict и UserContext.

    Формы пользователя разные: AuthMiddleware кладёт в g.user UserContext, а
    to_dict() и служебные вызовы — словарь. Признака администратора здесь нет:
    шлюз больше не шлёт X-User-Admin, и роль 'admin' сама по себе доступа не
    даёт — админ носит обычное право 'finder.*'.
    """
    return _extract_permissions(user)


def permission_granted(permission_name, permissions):
    """Проверяет локальное имя права по списку из шлюза, с учётом шаблонов.

    Локальные имена ('projects_info_update') отличаются от шлюзовых
    ('finder.projects_info_update') — переводим через PERMISSION_MAP, дальше
    сравнение делает общая реализация auth-connector: точное совпадение,
    голая '*' и префиксные шаблоны вида 'finder.*'.
    """
    gateway_perm = PERMISSION_MAP.get(permission_name, permission_name)
    return _granted(gateway_perm, permissions)


def any_permission_granted(permission_names, permissions):
    """Хватает любого права из списка."""
    permissions = list(permissions or ())
    return any(permission_granted(name, permissions) for name in permission_names)


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

            if permission_granted(permission_name, user_permissions(user)):
                return fn(*args, **kwargs)
            abort(403)

        return decorated_view
    return wrapper


def permission_required_any(*permission_names):
    """Пускает, если есть любое из перечисленных прав.

    Нужен там, где страница открывается и на просмотр, и на редактирование:
    право на правку подразумевает просмотр, но обратное неверно, а один
    декоратор с правом на правку заставлял выдавать доступ к записи только
    ради чтения. Саму запись роут проверяет отдельно — см. can_edit.
    """
    def wrapper(fn):
        @wraps(fn)
        def decorated_view(*args, **kwargs):
            user = _get_current_user()
            if not user or not _is_gateway_user(user):
                abort(401)

            if any_permission_granted(permission_names, user_permissions(user)):
                return fn(*args, **kwargs)
            abort(403)

        return decorated_view
    return wrapper


def current_user_can(permission_name):
    """Есть ли право у текущего пользователя. Для проверок внутри обработчика."""
    user = _get_current_user()
    if not user or not _is_gateway_user(user):
        return False
    return permission_granted(permission_name, user_permissions(user))


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