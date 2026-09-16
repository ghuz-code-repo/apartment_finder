# app/models/marketing_models.py
"""Таблицы витрины MacroData, нужные маркетинговому разделу.

Раньше из витрины читались только заявки, лог статусов, объекты и финансы.
Здесь добавлены звонки, отчёты о встречах и контакты — без них не собрать ни
динамику колл-центра, ни выгрузку контактов из воронки.

Ключи в витрине двойные, и связи у таблиц разные: лог статусов и звонки
ссылаются на estate_buys.id, а встречи — на estate_buys.estate_buy_id.
Перепутать их легко, поэтому в модели заявки есть оба поля.
"""

from app.core.extensions import db

from . import auth_models


class Call(db.Model):
    """Звонок телефонии."""
    __bind_key__ = 'mysql_source'
    __tablename__ = 'calls'

    id = db.Column(db.Integer, primary_key=True)
    calls_id = db.Column(db.Integer, nullable=True, index=True)
    call_date = db.Column(db.DateTime, index=True)
    calls_status = db.Column(db.String(16))
    # in — входящий, out — исходящий, internal — внутренний.
    direction = db.Column(db.String(16))
    phone = db.Column(db.String(16))
    contacts_id = db.Column(db.Integer, nullable=True, index=True)
    # Менеджер, который принял или совершил звонок.
    manager_id = db.Column(db.Integer, db.ForeignKey(auth_models.SalesManager.id),
                           nullable=True, index=True)
    first_manager_id = db.Column(db.Integer, nullable=True)
    # Заявка звонка ссылается на estate_buys.id.
    estate_id = db.Column(db.Integer, nullable=True, index=True)
    duration = db.Column(db.Integer)
    is_first_unique = db.Column(db.Integer, nullable=True)
    is_no_target = db.Column(db.Integer)
    is_hidden = db.Column(db.Integer)
    is_group_call = db.Column(db.Integer)

    def __repr__(self):
        return f'<Call {self.id} {self.direction} {self.calls_status}>'


class EstateMeeting(db.Model):
    """Отчёт о встрече: именно он фиксирует, что встреча была."""
    __bind_key__ = 'mysql_source'
    __tablename__ = 'estate_meetings'

    id = db.Column(db.Integer, primary_key=True)
    meetings_id = db.Column(db.Integer, nullable=True, index=True)
    # Внимание: ссылается на estate_buys.estate_buy_id, а не на estate_buys.id.
    estate_buy_id = db.Column(db.Integer, nullable=True, index=True)
    contacts_id = db.Column(db.Integer, nullable=True)
    manager_id = db.Column('users_id', db.Integer,
                           db.ForeignKey(auth_models.SalesManager.id),
                           nullable=True, index=True)
    date_added = db.Column(db.DateTime)
    # Дата учёта встречи — по ней и считаем, а не по дате добавления отчёта.
    meeting_date = db.Column(db.DateTime, index=True)
    meeting_type_place = db.Column(db.String(16))
    meeting_type_name = db.Column(db.String(48))
    complex_id = db.Column(db.Integer, nullable=True)
    house_id = db.Column(db.Integer, nullable=True, index=True)
    # Встреча могла не состояться — такие в «состоявшиеся» не идут.
    no_meeting = db.Column(db.Integer, nullable=True)
    is_first_meeting = db.Column(db.Integer)
    is_last_meeting = db.Column(db.Integer)

    def __repr__(self):
        return f'<EstateMeeting {self.id} buy={self.estate_buy_id}>'


class Task(db.Model):
    """Задача CRM. Назначенная встреча в Macro — задача типа «встреча».

    estate_id общий для заявок, объектов и домов, поэтому к заявке задачу
    привязываем по estate_buys.estate_buy_id вместе с типом задачи.
    """
    __bind_key__ = 'mysql_source'
    __tablename__ = 'tasks'

    id = db.Column(db.Integer, primary_key=True)
    estate_id = db.Column(db.Integer, nullable=True, index=True)
    contacts_id = db.Column(db.Integer, nullable=True)
    date_added = db.Column(db.Date)
    date_finish = db.Column(db.Date)
    # Встреча в офисе — meeting, на объекте — meeting_house.
    custom_type = db.Column(db.String(16))
    custom_type_name = db.Column(db.String(48))
    is_closed = db.Column(db.Integer)
    manager_id = db.Column(db.Integer, nullable=True)

    def __repr__(self):
        return f'<Task {self.id} {self.custom_type}>'


class Contact(db.Model):
    """Контакт клиента.

    Витрина может отдавать персональные данные обезличенными: их передача
    включается на стороне Macro отдельно. Поэтому пустые ФИО и телефон — не
    ошибка выгрузки, а настройка доступа.
    """
    __bind_key__ = 'mysql_source'
    __tablename__ = 'contacts'

    id = db.Column(db.Integer, primary_key=True)
    contacts_id = db.Column(db.Integer, nullable=True, index=True)
    full_name = db.Column('contacts_buy_name', db.String(255))
    name_last = db.Column(db.String(32))
    name_first = db.Column(db.String(32))
    name_middle = db.Column(db.String(32))
    phones = db.Column('contacts_buy_phones', db.String(255))
    emails = db.Column('contacts_buy_emails', db.String(255))

    def __repr__(self):
        return f'<Contact {self.id}>'
