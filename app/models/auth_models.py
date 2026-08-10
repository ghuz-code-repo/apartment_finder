# app/models/auth_models.py
# Local auth models removed — all authentication is handled by the gateway.
# Only SalesManager (MySQL source) remains here.

from app.core.extensions import db
from sqlalchemy.orm import relationship


class SalesManager(db.Model):
    # --- ЭТО МЕНЕДЖЕР ИЗ MYSQL (mysql_source) ---
    __bind_key__ = 'mysql_source'
    __tablename__ = 'users'  # <-- Указываем на таблицу 'users' в MySQL

    id = db.Column(db.Integer, primary_key=True)

    # --- ИСПРАВЛЕНИЕ ЗДЕСЬ ---
    # Мы говорим SQLAlchemy:
    # "Свойство 'full_name' в Python соответствует столбцу 'users_name' в MySQL"
    full_name = db.Column('users_name', db.String(255), nullable=False)
    # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

    post_title = db.Column(db.String(255), nullable=True)

    # Связь с ManagerSalesPlan (в planning_models)
    plans = db.relationship(
        'app.models.planning_models.ManagerSalesPlan',
        primaryjoin='SalesManager.id == foreign(app.models.planning_models.ManagerSalesPlan.manager_id)',
        back_populates='manager',
        viewonly=True,
        overlaps='manager'
    )