# app/models/funnel_models.py
from app.core.extensions import db

from . import auth_models


class EstateBuy(db.Model):
    __tablename__ = 'estate_buys'

    id = db.Column(db.Integer, primary_key=True)
    # Дата создания заявки. Раньше в источнике было поле date_added (DATE),
    # сейчас его нет — единственная дата создания это created_at (DATETIME).
    created_at = db.Column(db.DateTime)
    status_name = db.Column(db.String(32))
    custom_status_name = db.Column(db.String(255))

    # ============================================
    # === НАЧАЛО ИЗМЕНЕНИЙ: Добавляем поля ===
    # ============================================

    # ID дома (для связи с ЖК)
    house_id = db.Column(db.Integer, nullable=True)

    # ID кастомного статуса (для "Назначена встреча = 616")
    status_custom = db.Column(db.Integer, nullable=True)

    # ============================================
    # === КОНЕЦ ИЗМЕНЕНИЙ ===
    # ============================================

    __bind_key__ = 'mysql_source'


class EstateBuysStatusLog(db.Model):
    __tablename__ = 'estate_buys_statuses_log'

    # --- ИСПРАВЛЕНИЕ ЗДЕСЬ: УДАЛИ ЭТУ ДУБЛИРУЮЩУЮСЯ СТРОКУ ---
    # manager_id = db.Column(db.Integer, db.ForeignKey('sales_managers.id'), nullable=True)
    # --------------------------------------------------

    id = db.Column(db.Integer, primary_key=True)
    log_date = db.Column(db.DateTime)  # <-- Используем это поле для фильтрации
    estate_buy_id = db.Column(db.Integer)
    status_to_name = db.Column(db.String(32))
    status_custom_to_name = db.Column(db.String(255))

    # Столбец 'users_id' в MySQL ссылается на таблицу 'users' — её занимает
    # модель SalesManager. Ключ по имени 'sales_managers' указывал на таблицу,
    # которой нет ни в одной модели: SQLAlchemy не могла его разрешить и роняла
    # NoReferencedTableError на create_all и на любой записи через ORM.
    manager_id = db.Column(
        'users_id',
        db.Integer,
        db.ForeignKey(auth_models.SalesManager.id),
        nullable=True,
        index=True
    )
    __bind_key__ = 'mysql_source'