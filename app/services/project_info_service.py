# app/services/project_info_service.py

import os
import uuid

from flask import current_app
from werkzeug.utils import secure_filename
from PIL import Image

from ..core.db_utils import get_planning_session
from ..core.media import media_dir, media_url
from app.models.planning_models import ProjectInfo, ProjectRender

# --- Константы для загрузки рендеров ---
MAX_RENDERS = 5  # Максимум рендеров на один ЖК
UPLOAD_FOLDER = 'project_renders'  # Категория внутри UPLOAD_ROOT
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
MAX_IMAGE_WIDTH = 1920  # Максимальная ширина рендера в пикселях

# --- Требования к рендеру для КП ---
# На первой странице КП рендер занимает всю ширину листа в формате 16:9.
# Картинка другого соотношения обрежется по центру, поэтому при загрузке
# отклонение подсвечивается менеджеру.
KP_RENDER_RATIO = 16 / 9
KP_RENDER_RATIO_LABEL = '16:9'
KP_RENDER_RATIO_TOLERANCE = 0.06  # Допуск: примерно от 1.72:1 до 1.84:1
KP_RENDER_MIN_WIDTH = 1600  # Минимальная ширина, чтобы рендер не мылился в печати
KP_RENDER_RECOMMENDED = '1920×1080'
# Столько текста описания помещается на первую страницу КП рядом с рендером.
KP_DESCRIPTION_SOFT_LIMIT = 900

# Текстовые поля карточки проекта (заполняются как есть)
TEXT_FIELDS = [
    'project_class', 'developer', 'architect_bureau', 'location', 'website_url',
    'construction_tech', 'facade_materials', 'parking', 'infrastructure',
    'concept', 'description', 'usp',
]
INT_FIELDS = ['buildings_count', 'floors_min', 'floors_max']
FLOAT_FIELDS = ['ceiling_height', 'area_min', 'area_max']


def _allowed_file(filename):
    """Проверяет, имеет ли файл разрешенное расширение."""
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _renders_path():
    """Абсолютный путь к папке с рендерами."""
    return media_dir(UPLOAD_FOLDER)


def get_render_url(filename):
    """Ссылка на файл рендера. Отдаётся под авторизацией через роут media."""
    return media_url(f'{UPLOAD_FOLDER}/{filename}')


def _optimize_and_save_image(image_file_storage):
    """Оптимизирует и сохраняет рендер.

    Возвращает (имя файла, ширина, высота) уже сохраненного изображения:
    размеры нужны, чтобы проверить пригодность рендера для первой страницы КП.
    """
    if not image_file_storage or not image_file_storage.filename:
        raise ValueError("Файл не выбран.")

    if not _allowed_file(image_file_storage.filename):
        raise ValueError(
            f"Недопустимый формат файла '{image_file_storage.filename}'. "
            f"Разрешены: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
        )

    base_name = os.path.splitext(secure_filename(image_file_storage.filename))[0] or 'render'
    # Уникальное имя, чтобы файлы разных проектов не перезаписывали друг друга
    unique_filename = f"{base_name}_{uuid.uuid4().hex[:12]}.webp"

    upload_path = _renders_path()
    os.makedirs(upload_path, exist_ok=True)
    full_path = os.path.join(upload_path, unique_filename)

    img = Image.open(image_file_storage)

    # Конвертируем в RGB для совместимости с WebP
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    # Уменьшаем слишком большие изображения
    if img.width > MAX_IMAGE_WIDTH:
        ratio = MAX_IMAGE_WIDTH / float(img.width)
        new_height = int(float(img.height) * ratio)
        img = img.resize((MAX_IMAGE_WIDTH, new_height), Image.LANCZOS)

    img.save(full_path, 'WEBP', quality=85)
    return unique_filename, img.width, img.height


def _delete_render_file(filename):
    """Удаляет файл рендера с диска (молча, если файла уже нет)."""
    if not filename:
        return
    try:
        os.remove(os.path.join(_renders_path(), filename))
    except OSError:
        current_app.logger.warning(f"Не удалось удалить файл рендера: {filename}")


def _to_int(value):
    """'12' -> 12, пустая строка / мусор -> None."""
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    try:
        return int(float(value.replace(',', '.')))
    except ValueError:
        return None


def _to_float(value):
    """'2,9' -> 2.9, пустая строка / мусор -> None."""
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    try:
        return float(value.replace(',', '.'))
    except ValueError:
        return None


def get_project_info(complex_name):
    """Возвращает карточку проекта или None, если она еще не заполнялась."""
    planning_session = get_planning_session()
    return planning_session.query(ProjectInfo).get(complex_name)


def get_or_create_project_info(complex_name):
    """Возвращает карточку проекта, создавая пустую при первом обращении."""
    planning_session = get_planning_session()
    info = planning_session.query(ProjectInfo).get(complex_name)
    if not info:
        info = ProjectInfo(complex_name=complex_name)
        planning_session.add(info)
        planning_session.flush()
    return info


def get_renders(complex_name):
    """Список рендеров проекта в порядке сортировки."""
    planning_session = get_planning_session()
    return planning_session.query(ProjectRender).filter_by(
        complex_name=complex_name
    ).order_by(ProjectRender.sort_order.asc(), ProjectRender.id.asc()).all()


def save_project_info(complex_name, form_data):
    """
    Сохраняет характеристики ЖК.
    form_data — request.form (или обычный словарь).
    """
    planning_session = get_planning_session()
    info = get_or_create_project_info(complex_name)

    for field in TEXT_FIELDS:
        value = (form_data.get(field) or '').strip()
        setattr(info, field, value or None)

    for field in INT_FIELDS:
        setattr(info, field, _to_int(form_data.get(field)))

    for field in FLOAT_FIELDS:
        setattr(info, field, _to_float(form_data.get(field)))

    planning_session.commit()
    return info


def kp_requirements_problem(width, height):
    """Что не так с рендером для первой страницы КП. None — всё в порядке."""
    if not width or not height:
        return None  # Размеры неизвестны (рендер загружен до появления проверки)

    if width < KP_RENDER_MIN_WIDTH:
        return (f"ширина {width}px меньше {KP_RENDER_MIN_WIDTH}px — "
                f"в печати рендер будет мылить")

    ratio = width / height
    if abs(ratio - KP_RENDER_RATIO) > KP_RENDER_RATIO_TOLERANCE:
        return (f"соотношение сторон {ratio:.2f}:1 вместо {KP_RENDER_RATIO_LABEL} — "
                f"на первой странице КП рендер обрежется по центру")

    return None


def describe_render(render):
    """Данные о рендере для страницы настроек: размер и пригодность для КП."""
    problem = kp_requirements_problem(render.width, render.height)
    return {
        'size': f"{render.width}×{render.height}" if render.width and render.height else None,
        'ratio': f"{render.width / render.height:.2f}:1" if render.width and render.height else None,
        'problem': problem,
        'ok': problem is None and bool(render.width),
    }


def set_cover_render(complex_name, render_id):
    """Делает выбранный рендер первым — именно он уходит на первую страницу КП."""
    if not render_id:
        return False

    try:
        render_id = int(render_id)
    except (TypeError, ValueError):
        return False

    renders = get_renders(complex_name)
    if not any(r.id == render_id for r in renders):
        return False

    planning_session = get_planning_session()
    order = 0
    # Выбранный рендер получает нулевой порядок, остальные сохраняют относительный.
    for render in sorted(renders, key=lambda r: (r.id != render_id, r.sort_order, r.id)):
        render.sort_order = order
        order += 1

    planning_session.commit()
    return True


def add_renders(complex_name, files):
    """
    Добавляет рендеры к проекту (не больше MAX_RENDERS всего).
    Возвращает (количество добавленных, список сообщений об ошибках).
    """
    planning_session = get_planning_session()
    get_or_create_project_info(complex_name)

    existing = get_renders(complex_name)
    free_slots = MAX_RENDERS - len(existing)
    next_order = (max([r.sort_order for r in existing]) + 1) if existing else 0

    files = [f for f in (files or []) if f and f.filename]
    errors = []
    added = 0

    if not files:
        return 0, errors

    if free_slots <= 0:
        return 0, [f"Достигнут лимит в {MAX_RENDERS} рендеров. Удалите лишние, чтобы загрузить новые."]

    if len(files) > free_slots:
        errors.append(
            f"Загружено только {free_slots} из {len(files)} файлов: "
            f"максимум {MAX_RENDERS} рендеров на проект."
        )
        files = files[:free_slots]

    for file_storage in files:
        original_name = file_storage.filename
        try:
            filename, width, height = _optimize_and_save_image(file_storage)
        except ValueError as e:
            errors.append(str(e))
            continue
        except Exception as e:
            current_app.logger.error(f"Ошибка обработки рендера для {complex_name}: {e}")
            errors.append(f"Не удалось обработать файл '{original_name}'.")
            continue

        # Не блокируем загрузку: рендер может понадобиться и вне КП, но о том,
        # что на первой странице он обрежется, менеджер должен узнать сразу.
        problem = kp_requirements_problem(width, height)
        if problem:
            errors.append(f"«{original_name}»: {problem}")

        planning_session.add(ProjectRender(
            complex_name=complex_name,
            filename=filename,
            width=width,
            height=height,
            sort_order=next_order
        ))
        next_order += 1
        added += 1

    planning_session.commit()
    return added, errors


def update_render_titles(complex_name, titles_by_id):
    """Обновляет подписи к рендерам. titles_by_id: {render_id: 'подпись'}."""
    if not titles_by_id:
        return 0

    planning_session = get_planning_session()
    updated = 0
    for render in get_renders(complex_name):
        if render.id in titles_by_id:
            title = (titles_by_id[render.id] or '').strip()
            render.title = title or None
            updated += 1

    planning_session.commit()
    return updated


def delete_renders(complex_name, render_ids):
    """Удаляет рендеры проекта вместе с файлами. Возвращает количество удаленных."""
    render_ids = [int(rid) for rid in (render_ids or [])]
    if not render_ids:
        return 0

    planning_session = get_planning_session()
    renders = planning_session.query(ProjectRender).filter(
        ProjectRender.complex_name == complex_name,
        ProjectRender.id.in_(render_ids)
    ).all()

    for render in renders:
        _delete_render_file(render.filename)
        planning_session.delete(render)

    planning_session.commit()
    return len(renders)
