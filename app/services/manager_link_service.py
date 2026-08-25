# app/services/manager_link_service.py
"""Кто из менеджеров CRM стоит за текущим пользователем.

Пользователи живут в шлюзе, менеджеры продаж — в MySQL Macro, общего
идентификатора нет. По умолчанию сопоставляем по ФИО, а тёзок, опечатки и
расхождения в написании админ разводит руками — ручная связка всегда сильнее
автоматической.
"""

import re

from ..core.db_utils import get_planning_session, get_mysql_session
from ..core.decorators import current_user_identity
from app.models.auth_models import SalesManager
from app.models.planning_models import ManagerUserLink


def _normalize(name):
    """ФИО в сравнимый вид: регистр, лишние пробелы и 'ё' не должны мешать."""
    if not name:
        return ''
    return re.sub(r'\s+', ' ', str(name).strip().lower().replace('ё', 'е'))


def get_link(username):
    """Явная связка пользователя, если админ её заводил."""
    if not username:
        return None
    return get_planning_session().query(ManagerUserLink).get(str(username))


def find_manager_by_full_name(full_name):
    """Менеджер CRM с таким же ФИО. Тёзки -> None: пусть свяжут руками."""
    target = _normalize(full_name)
    if not target:
        return None

    managers = get_mysql_session().query(SalesManager).all()
    matches = [m for m in managers if _normalize(m.full_name) == target]
    return matches[0] if len(matches) == 1 else None


def resolve_manager_id(username, full_name):
    """id менеджера CRM для пользователя. None — сопоставить не удалось."""
    link = get_link(username)
    if link:
        return link.manager_id

    manager = find_manager_by_full_name(full_name)
    return manager.id if manager else None


def current_manager_id():
    """id менеджера CRM для текущего пользователя."""
    username, full_name = current_user_identity()
    return resolve_manager_id(username, full_name)


def current_manager():
    """Сам менеджер CRM для текущего пользователя."""
    manager_id = current_manager_id()
    if not manager_id:
        return None
    return get_mysql_session().query(SalesManager).get(manager_id)


def set_link(username, manager_id):
    """Связывает пользователя с менеджером вручную."""
    username = (username or '').strip()
    if not username or not manager_id:
        return False

    planning_session = get_planning_session()
    manager = get_mysql_session().query(SalesManager).get(int(manager_id))
    if not manager:
        return False

    link = planning_session.query(ManagerUserLink).get(username)
    if not link:
        link = ManagerUserLink(username=username)
        planning_session.add(link)

    link.manager_id = manager.id
    link.full_name = manager.full_name
    planning_session.commit()
    return True


def clear_link(username):
    """Убирает ручную связку — пользователь снова сопоставляется по ФИО."""
    planning_session = get_planning_session()
    link = planning_session.query(ManagerUserLink).get((username or '').strip())
    if not link:
        return False

    planning_session.delete(link)
    planning_session.commit()
    return True


def list_managers_with_links(search=None):
    """Менеджеры CRM и связанные с ними логины — для страницы настройки."""
    managers_query = get_mysql_session().query(SalesManager)
    if search:
        managers_query = managers_query.filter(SalesManager.full_name.ilike(f'%{search}%'))
    managers = managers_query.order_by(SalesManager.full_name).all()

    links_by_manager = {}
    for link in get_planning_session().query(ManagerUserLink).all():
        links_by_manager.setdefault(link.manager_id, []).append(link.username)

    return [
        {
            'manager': manager,
            'usernames': sorted(links_by_manager.get(manager.id, [])),
        }
        for manager in managers
    ]
