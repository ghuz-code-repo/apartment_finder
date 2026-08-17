"""Общие пути и ссылки для загруженных файлов.

Файлы лежат в UPLOAD_ROOT (том ./uploads), а не в static: блок
`location {prefix}/static/` в шаблоне nginx идёт без auth_request, и всё
внутри него скачивалось анонимно. Отдаёт файлы роут media.file, он проверяет
права по категории — первому сегменту относительного пути.
"""

import os

from flask import current_app, url_for

# Категория -> права, любого из которых достаточно для чтения файлов.
# Рендеры и планировки попадают в КП, поэтому у них в списке есть право на КП:
# менеджер, который смотрит только КП, иначе получил бы вместо картинок дыры.
MEDIA_PERMISSIONS = {
    'project_renders': ('projects_dashboard_view', 'projects_passport_view',
                        'projects_info_view', 'projects_info_update',
                        'selection_commercial_offer_view'),
    'floor_plans': ('specials_view', 'specials_update', 'selection_specials_view',
                    'selection_commercial_offer_view'),
    'competitors': ('competitors_profile_view',),
    'news': ('news_view',),
}


def upload_root():
    """Абсолютный путь к корню загрузок."""
    return current_app.config['UPLOAD_ROOT']


def media_dir(*parts):
    """Абсолютный путь к подкаталогу загрузок, с созданием при необходимости."""
    path = os.path.join(upload_root(), *parts)
    os.makedirs(path, exist_ok=True)
    return path


def normalize_relpath(relpath):
    """Путь от корня загрузок в едином виде.

    Медиа конкурентов и новостей хранят file_path в БД, и старые записи были
    сделаны относительно static — с ведущим 'uploads/'. Корнем теперь служит
    сам каталог uploads, поэтому префикс срезаем: иначе категория определится
    как 'uploads' и файл не отдастся.
    """
    relpath = (relpath or '').replace(os.sep, '/').lstrip('/')
    if relpath.startswith('uploads/'):
        relpath = relpath[len('uploads/'):]
    return relpath


def media_url(relpath):
    """Ссылка на файл под авторизацией. relpath — путь от корня загрузок."""
    return url_for('media.file', relpath=normalize_relpath(relpath))


def resolve_media_path(relpath):
    """Абсолютный путь внутри UPLOAD_ROOT либо None, если путь уводит наружу.

    Проверяем именно итоговый путь после normpath: '..' в relpath и симлинк
    внутри каталога загрузок оба дали бы чтение произвольного файла.
    """
    root = os.path.realpath(upload_root())
    candidate = os.path.realpath(os.path.join(root, normalize_relpath(relpath)))
    if candidate != root and not candidate.startswith(root + os.sep):
        return None
    return candidate