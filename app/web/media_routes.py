"""Отдача загруженных файлов под авторизацией.

Раньше эти файлы лежали в static и уходили любому, кто знал адрес: блок
`location {prefix}/static/` в шаблоне nginx не имеет auth_request, да ещё и
кэширует ответ на час. Здесь каждый файл проходит login_required и проверку
права на свою категорию.
"""

import os

from flask import Blueprint, abort, send_file

from ..core.decorators import any_permission_granted, login_required, user_permissions
from ..core.decorators import _get_current_user, _is_gateway_user
from ..core.media import MEDIA_PERMISSIONS, normalize_relpath, resolve_media_path

media_bp = Blueprint('media', __name__)

# Как долго браузер может держать файл у себя. Ссылки на загрузки неизменяемые
# (имя файла содержит уникальный суффикс), поэтому час безопасен.
CACHE_TTL = 3600


@media_bp.route('/media/<path:relpath>')
@login_required
def file(relpath):
    """Отдаёт файл из UPLOAD_ROOT, если у пользователя есть право на категорию."""
    category = normalize_relpath(relpath).split('/', 1)[0]
    required = MEDIA_PERMISSIONS.get(category)
    if not required:
        # Неизвестный каталог не открываем: любой новый вид загрузок должен
        # сначала получить запись в MEDIA_PERMISSIONS.
        abort(404)

    user = _get_current_user()
    if not user or not _is_gateway_user(user):
        abort(401)
    if not any_permission_granted(required, user_permissions(user)):
        abort(403)

    full_path = resolve_media_path(relpath)
    if not full_path or not os.path.isfile(full_path):
        abort(404)

    return send_file(full_path, max_age=CACHE_TTL, conditional=True)
