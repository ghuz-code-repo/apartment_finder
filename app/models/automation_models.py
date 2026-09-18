# app/models/automation_models.py
"""Автоматические действия в CRM и их журнал.

Первое такое действие — «страж встреч»: при переходе заявки в «Сделку в
работе» проверяет, была ли встреча за последние три месяца, и если нет —
ставит задачу-встречу менеджеру сделки. Журнал нужен, чтобы одно и то же
действие не выполнилось дважды и чтобы было видно, почему для конкретной
сделки встречу создали или не создали.
"""

from sqlalchemy import func

from app.core.extensions import db


class AutomationState(db.Model):
    """Состояние фоновых автоматизаций: момент включения, последний опрос."""
    __bind_key__ = 'planning_db'
    __tablename__ = 'automation_state'

    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.String(255))
    updated_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AutoMeetingLog(db.Model):
    """Решение стража встреч по одной сделке."""
    __bind_key__ = 'planning_db'
    __tablename__ = 'auto_meeting_log'
    __table_args__ = (db.UniqueConstraint('estate_buy_id', 'deal_id', name='uq_auto_meeting_deal'),)

    id = db.Column(db.Integer, primary_key=True)
    estate_buy_id = db.Column(db.Integer, nullable=False, index=True)
    deal_id = db.Column(db.Integer, nullable=False)
    house_id = db.Column(db.Integer)
    manager_id = db.Column(db.Integer)
    # Когда заявка перешла в «Сделку в работе» (по дате изменения сделки).
    moved_at = db.Column(db.DateTime)

    # created — встреча создана; has_meeting — встреча уже была;
    # before_enable — переход раньше включения; dry_run — создали бы;
    # error — не получилось, повторим.
    decision = db.Column(db.String(32), nullable=False, index=True)
    task_id = db.Column(db.Integer)
    found_task_id = db.Column(db.Integer)
    notified = db.Column(db.Boolean, default=False)
    error = db.Column(db.Text)
    attempts = db.Column(db.Integer, default=0, nullable=False)

    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())
    updated_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f'<AutoMeetingLog {self.estate_buy_id}/{self.deal_id} {self.decision}>'
