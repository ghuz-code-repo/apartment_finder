# app/models/funnel_models.py
from app.core.extensions import db

from . import auth_models


class EstateBuy(db.Model):
    __tablename__ = 'estate_buys'

    id = db.Column(db.Integer, primary_key=True)
    # Второй ключ витрины. Лог статусов и звонки ссылаются на id, а отчёты о
    # встречах — на estate_buy_id, поэтому в модели нужны оба.
    estate_buy_id = db.Column(db.Integer, nullable=True, index=True)

    # Дата создания заявки. Раньше в источнике было поле date_added (DATE),
    # сейчас его нет — единственная дата создания это created_at (DATETIME).
    created_at = db.Column(db.DateTime)
    status_name = db.Column(db.String(32))
    custom_status_name = db.Column(db.String(255))

    # Дом объекта в сделке. Заполняется только начиная с брони, поэтому
    # проект новой заявки по нему не определить — для этого поля интереса ниже.
    house_id = db.Column(db.Integer, nullable=True)
    # Первый интерес заявки: комплекс и дом, которыми клиент заинтересовался.
    first_complex_interest = db.Column(db.Integer, nullable=True)
    first_house_interest = db.Column(db.Integer, nullable=True)

    # ID кастомного статуса (для "Назначена встреча = 616")
    status_custom = db.Column(db.Integer, nullable=True)
    # Числовой статус витрины: 20 — Подбор, 30 — Бронь, 100 — Сделка проведена.
    status = db.Column(db.Integer, nullable=True)

    # Контакт клиента — по нему собирается выгрузка из воронки.
    contacts_id = db.Column(db.Integer, nullable=True, index=True)

    # Менеджер заявки и отдельно менеджер колл-центра: в отчёте колл-центра
    # интересен именно второй, но заполнен он не всегда.
    manager_id = db.Column(db.Integer, db.ForeignKey(auth_models.SalesManager.id),
                           nullable=True, index=True)
    call_center_manager_id = db.Column(db.Integer, nullable=True, index=True)

    # Канал заявки: витрина уже разложила источник, сопоставлять utm руками
    # не нужно.
    channel_type = db.Column(db.String(32), nullable=True)
    channel_name = db.Column(db.String(255), nullable=True)
    utm_source = db.Column(db.String(255), nullable=True)
    utm_medium = db.Column(db.String(255), nullable=True)
    utm_campaign = db.Column(db.String(255), nullable=True)

    __bind_key__ = "mysql_source"


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