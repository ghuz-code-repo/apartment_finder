# app/services/marketing_funnel_service.py
"""Воронка маркетингового портала: этапы, конверсии и выгрузка контактов.

От воронки в отчётах отличается задачей. Там дерево путей и сравнение когорт —
инструмент аналитика. Здесь линейная воронка, из которой маркетолог забирает
сегмент контактов для повторного офера, поэтому этап кликабелен, а список
выгружается в Excel.

Заявка считается прошедшей этап, если такой переход есть в логе статусов, а не
по текущему статусу: иначе дошедшие до сделки исчезли бы из всех предыдущих
этапов и конверсии считались бы от неполной базы.
"""

import io
from datetime import timedelta

from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import func

from ..core.dates import to_date
from ..core.db_utils import get_mysql_session
from app.models.auth_models import SalesManager
from app.models.estate_models import EstateHouse
from app.models.funnel_models import EstateBuy, EstateBuysStatusLog
from app.models.marketing_models import Contact, EstateMeeting

# Этапы воронки по порядку. Для каждого — как определяется прохождение:
# статус в логе, подстатус или отчёт о встрече.
STAGES = (
    {'key': 'lead', 'title': 'Заявка', 'source': 'all'},
    {'key': 'selection', 'title': 'Подбор', 'source': 'status', 'status': 'Подбор'},
    {'key': 'meeting_set', 'title': 'Встреча назначена', 'source': 'custom_status',
     'custom_status': 'Назначена встреча'},
    {'key': 'meeting_held', 'title': 'Визит состоялся', 'source': 'meeting'},
    {'key': 'booking', 'title': 'Бронь', 'source': 'status', 'status': 'Бронь'},
    {'key': 'deal', 'title': 'Сделка', 'source': 'status',
     'status': ('Сделка в работе', 'Сделка проведена')},
)
STAGE_BY_KEY = {stage['key']: stage for stage in STAGES}


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

    if complexes:
        house_ids = [row[0] for row in mysql_session.query(EstateHouse.id).filter(
            EstateHouse.complex_name.in_(complexes)).all()]
        # Пустой список означает, что ни один проект не подошёл: показывать
        # всё, как будто фильтра нет, нельзя.
        query = query.filter(EstateBuy.house_id.in_(house_ids or [0]))
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

    if source == 'meeting':
        # Встречу подтверждает отчёт, а он ссылается на второй ключ заявки.
        buy_keys = dict(mysql_session.query(EstateBuy.estate_buy_id, EstateBuy.id).filter(
            EstateBuy.id.in_(cohort_ids)).all())
        rows = mysql_session.query(EstateMeeting.estate_buy_id).filter(
            EstateMeeting.estate_buy_id.in_(list(buy_keys.keys()) or [0]),
            (EstateMeeting.no_meeting.is_(None)) | (EstateMeeting.no_meeting == 0),
        ).distinct().all()
        return {buy_keys[row[0]] for row in rows if row[0] in buy_keys}

    query = mysql_session.query(EstateBuysStatusLog.estate_buy_id).filter(
        EstateBuysStatusLog.estate_buy_id.in_(cohort_query))

    if source == 'status':
        statuses = stage['status']
        statuses = statuses if isinstance(statuses, tuple) else (statuses,)
        query = query.filter(EstateBuysStatusLog.status_to_name.in_(statuses))
    else:
        query = query.filter(EstateBuysStatusLog.status_custom_to_name == stage['custom_status'])

    return {row[0] for row in query.distinct().all()}


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
        contacts = {c.contacts_id or c.id: c for c in mysql_session.query(Contact).filter(
            Contact.contacts_id.in_(contact_ids)).all()}

    house_ids = {lead.house_id for lead in leads if lead.house_id}
    houses = {}
    if house_ids:
        houses = {h.id: h for h in mysql_session.query(EstateHouse).filter(
            EstateHouse.id.in_(house_ids)).all()}

    managers = {m.id: m.full_name for m in mysql_session.query(SalesManager).all()}

    last_actions = dict(mysql_session.query(
        EstateBuysStatusLog.estate_buy_id, func.max(EstateBuysStatusLog.log_date)
    ).filter(EstateBuysStatusLog.estate_buy_id.in_(stage_ids)).group_by(
        EstateBuysStatusLog.estate_buy_id).all())

    rows = []
    for lead in leads:
        contact = contacts.get(lead.contacts_id)
        house = houses.get(lead.house_id)
        rows.append({
            'lead_id': lead.id,
            'contact_name': (contact.full_name if contact else None) or '—',
            'phone': (contact.phones if contact else None) or '—',
            'complex_name': (house.complex_name if house else None) or '—',
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
