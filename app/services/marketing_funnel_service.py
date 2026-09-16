# app/services/marketing_funnel_service.py
"""Воронка маркетингового портала: этапы, конверсии и выгрузка контактов.

От воронки в отчётах отличается задачей. Там дерево путей и сравнение когорт —
инструмент аналитика. Здесь линейная воронка, из которой маркетолог забирает
сегмент контактов для повторного офера, поэтому этап кликабелен, а список
выгружается в Excel.

Откуда берётся каждый этап:

* заявки — таблица estate_buys, проект по полям интереса (см. lead_projects);
* встречи — свои таблицы витрины: назначенная встреча — задача типа «встреча»
  (tasks) или отчёт о встрече, состоявшаяся — отчёт без признака no_meeting
  (estate_meetings). Подстатусы в логе переименовываются в настройках CRM, и
  поиск по названию давал ноль;
* подбор, бронь и сделка — переходы в логе статусов по заявкам выбранной
  когорты, а не текущий статус: иначе дошедшие до сделки исчезли бы из всех
  предыдущих этапов и конверсии считались бы от неполной базы.
"""

import io
from datetime import timedelta

from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import func, or_

from ..core.dates import to_date
from ..core.db_utils import get_mysql_session
from app.models.auth_models import SalesManager
from app.models.estate_models import EstateHouse
from app.models.funnel_models import EstateBuy, EstateBuysStatusLog
from app.models.marketing_models import Contact, EstateMeeting, Task
from .lead_projects import lead_project_condition, project_names_for

# Этапы воронки по порядку. Для каждого — как определяется прохождение:
# статус в логе либо таблица встреч.
STAGES = (
    {'key': 'lead', 'title': 'Заявка', 'source': 'all'},
    {'key': 'selection', 'title': 'Подбор', 'source': 'status', 'status': 'Подбор'},
    {'key': 'meeting_set', 'title': 'Встреча назначена', 'source': 'meeting_set'},
    {'key': 'meeting_held', 'title': 'Визит состоялся', 'source': 'meeting_held'},
    {'key': 'booking', 'title': 'Бронь', 'source': 'status', 'status': 'Бронь'},
    {'key': 'deal', 'title': 'Сделка', 'source': 'status',
     'status': ('Сделка в работе', 'Сделка проведена')},
)
STAGE_BY_KEY = {stage['key']: stage for stage in STAGES}

# Типы задач, которыми в Macro назначают встречу: в офисе и на объекте.
MEETING_TASK_TYPES = ('meeting', 'meeting_house')


def get_filter_options():
    """Проекты и каналы для фильтров."""
    mysql_session = get_mysql_session()
    complexes = [row[0] for row in mysql_session.query(EstateHouse.complex_name)
                 .filter(EstateHouse.complex_name.isnot(None))
                 .distinct().order_by(EstateHouse.complex_name).all()]
    # Канал витрина уже разложила — сопоставлять utm руками не нужно.
    channels = [row[0] for row in mysql_session.query(EstateBuy.channel_type)
                .filter(EstateBuy.channel_type.isnot(None))
                .distinct().order_by(EstateBuy.channel_type).all()]
    return {'complexes': complexes, 'channels': channels}


def _cohort_query(start_date, end_date, complexes=None, channels=None):
    """Заявки периода с учётом фильтров — основа всех этапов."""
    mysql_session = get_mysql_session()
    query = mysql_session.query(EstateBuy.id).filter(
        EstateBuy.created_at.isnot(None),
        EstateBuy.created_at >= start_date,
        EstateBuy.created_at < end_date + timedelta(days=1),
    )

    project_condition = lead_project_condition(complexes)
    if project_condition is not None:
        query = query.filter(project_condition)
    if channels:
        query = query.filter(EstateBuy.channel_type.in_(channels))

    return query


def _stage_ids(stage, cohort_ids, cohort_query):
    """id заявок, прошедших этап."""
    if not cohort_ids:
        return set()

    mysql_session = get_mysql_session()
    source = stage['source']

    if source == 'all':
        return set(cohort_ids)

    if source in ('meeting_set', 'meeting_held'):
        return _meeting_ids(source, cohort_ids)

    query = mysql_session.query(EstateBuysStatusLog.estate_buy_id).filter(
        EstateBuysStatusLog.estate_buy_id.in_(cohort_query))

    statuses = stage['status']
    statuses = statuses if isinstance(statuses, tuple) else (statuses,)
    query = query.filter(EstateBuysStatusLog.status_to_name.in_(statuses))

    return {row[0] for row in query.distinct().all()}


def _meeting_ids(source, cohort_ids):
    """Заявки когорты с назначенной или состоявшейся встречей — по таблицам встреч.

    Встречи и задачи ссылаются на второй ключ заявки (estate_buy_id), поэтому
    сначала строим соответствие ключей.
    """
    mysql_session = get_mysql_session()
    leads = mysql_session.query(EstateBuy.estate_buy_id, EstateBuy.id, EstateBuy.contacts_id).filter(
        EstateBuy.id.in_(cohort_ids), EstateBuy.estate_buy_id.isnot(None)).all()
    by_buy_key = {buy_key: (lead_id, contacts_id) for buy_key, lead_id, contacts_id in leads}
    if not by_buy_key:
        return set()
    buy_keys = list(by_buy_key)

    reports = mysql_session.query(EstateMeeting.estate_buy_id).filter(
        EstateMeeting.estate_buy_id.in_(buy_keys))
    if source == 'meeting_held':
        reports = reports.filter(or_(EstateMeeting.no_meeting.is_(None), EstateMeeting.no_meeting == 0))
    ids = {by_buy_key[row[0]][0] for row in reports.distinct().all()}
    if source == 'meeting_held':
        return ids

    # Назначенная встреча — задача-встреча, даже если отчёта по ней ещё нет.
    # Отчёт тоже считается: без назначения встречи он бы не появился.
    tasks = mysql_session.query(Task.estate_id, Task.contacts_id).filter(
        Task.estate_id.in_(buy_keys), Task.custom_type.in_(MEETING_TASK_TYPES)).all()
    for buy_key, task_contact in tasks:
        lead_id, lead_contact = by_buy_key[buy_key]
        # estate_id общий для заявок, объектов и домов: при несовпадении
        # контакта задача относится к другой сущности с тем же номером.
        if task_contact and lead_contact and task_contact != lead_contact:
            continue
        ids.add(lead_id)
    return ids


def get_funnel(start_date, end_date, complexes=None, channels=None):
    """Этапы воронки с конверсией между соседними."""
    cohort_query = _cohort_query(start_date, end_date, complexes, channels)
    cohort_ids = [row[0] for row in cohort_query.all()]

    stages = []
    previous_count = None
    for stage in STAGES:
        ids = _stage_ids(stage, cohort_ids, cohort_query)
        count = len(ids)
        stages.append({
            'key': stage['key'],
            'title': stage['title'],
            'count': count,
            # Конверсия к предыдущему этапу и доля от всех заявок: первая
            # показывает узкое место, вторая — сквозной результат.
            'from_previous': (round(count * 100 / previous_count, 1)
                              if previous_count else None),
            'from_total': (round(count * 100 / len(cohort_ids), 1)
                           if cohort_ids else None),
        })
        previous_count = count

    return {'stages': stages, 'total': len(cohort_ids)}


# --- Контакты этапа ---

def get_stage_contacts(stage_key, start_date, end_date, complexes=None, channels=None,
                       limit=None):
    """Контакты заявок, прошедших этап.

    Берём всех, кто прошёл этап за период, включая ушедших дальше по воронке:
    для повторного офера важен сам факт контакта на этапе. Если понадобится
    «кто застрял именно здесь» — это отдельный срез, а не замена этому.
    """
    stage = STAGE_BY_KEY.get(stage_key)
    if not stage:
        return []

    mysql_session = get_mysql_session()
    cohort_query = _cohort_query(start_date, end_date, complexes, channels)
    cohort_ids = [row[0] for row in cohort_query.all()]
    stage_ids = _stage_ids(stage, cohort_ids, cohort_query)
    if not stage_ids:
        return []

    stage_ids = sorted(stage_ids)
    if limit:
        stage_ids = stage_ids[:limit]

    leads = mysql_session.query(EstateBuy).filter(EstateBuy.id.in_(stage_ids)).all()

    # Справочники тянем пачками: по одному запросу на заявку страница бы встала.
    contact_ids = {lead.contacts_id for lead in leads if lead.contacts_id}
    contacts = {}
    if contact_ids:
        # По документации заявка ссылается на contacts.id, встречи — на
        # contacts.contacts_id; обычно они совпадают, но опираться на это не будем.
        for contact in mysql_session.query(Contact).filter(or_(
                Contact.id.in_(contact_ids), Contact.contacts_id.in_(contact_ids))).all():
            contacts.setdefault(contact.id, contact)
            if contact.contacts_id:
                contacts.setdefault(contact.contacts_id, contact)

    project_names = project_names_for(leads)

    managers = {m.id: m.full_name for m in mysql_session.query(SalesManager).all()}

    last_actions = dict(mysql_session.query(
        EstateBuysStatusLog.estate_buy_id, func.max(EstateBuysStatusLog.log_date)
    ).filter(EstateBuysStatusLog.estate_buy_id.in_(stage_ids)).group_by(
        EstateBuysStatusLog.estate_buy_id).all())

    rows = []
    for lead in leads:
        contact = contacts.get(lead.contacts_id)
        rows.append({
            'lead_id': lead.id,
            'contact_name': (contact.full_name if contact else None) or '—',
            'phone': (contact.phones if contact else None) or '—',
            'complex_name': project_names.get(lead.id) or '—',
            'stage': stage['title'],
            'channel': lead.channel_type or '—',
            'created_at': to_date(lead.created_at),
            'last_action': to_date(last_actions.get(lead.id)),
            'manager_name': managers.get(lead.manager_id) or '—',
        })

    rows.sort(key=lambda r: (r['last_action'] is None, r['last_action']), reverse=True)
    return rows


EXPORT_COLUMNS = (
    ('lead_id', 'Заявка'),
    ('contact_name', 'ФИО'),
    ('phone', 'Телефон'),
    ('complex_name', 'Проект'),
    ('stage', 'Этап'),
    ('channel', 'Канал'),
    ('last_action', 'Дата последнего контакта'),
    ('manager_name', 'Ответственный менеджер'),
)


def export_contacts_excel(rows, stage_title):
    """Выгрузка контактов этапа в Excel."""
    workbook = Workbook()
    sheet = workbook.active
    # Имя листа в Excel ограничено 31 символом и не терпит части знаков.
    sheet.title = stage_title[:31]

    sheet.append([title for _key, title in EXPORT_COLUMNS])
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    for row in rows:
        sheet.append([
            row[key].strftime('%d.%m.%Y') if key == 'last_action' and row[key] else row[key]
            for key, _title in EXPORT_COLUMNS
        ])

    widths = (10, 30, 20, 22, 20, 14, 26, 26)
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = width

    stream = io.BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream
