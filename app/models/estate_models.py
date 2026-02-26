# app/models/estate_models.py

from app.core.extensions import db


# --- ИСПРАВЛЕНИЕ: Импортируем auth_models, чтобы ссылка работала ---
# (Хотя он нам не нужен, если мы используем строки)
# from . import auth_models 
# (Лучше не импортировать, чтобы избежать цикла)


class EstateDeal(db.Model):
    __tablename__ = 'estate_deals'
    id = db.Column(db.Integer, primary_key=True)
    deal_date_start = db.Column(db.Date, nullable=True)
    estate_sell_id = db.Column(db.Integer, db.ForeignKey('estate_sells.id'), nullable=False)
    date_modified = db.Column(db.Date, nullable=True)
    deal_status_name = db.Column(db.String(100))
    agreement_number = db.Column(db.String(100), nullable=True)

    # --- ВОТ ИСПРАВЛЕНИЕ: ДОБАВЛЕНО ПОЛЕ ---
    deal_program_name = db.Column(db.String(255), nullable=True)
    # ------------------------------------

    agreement_date = db.Column(db.Date, nullable=True)
    preliminary_date = db.Column(db.Date, nullable=True)
    deal_sum = db.Column(db.Float, nullable=True)
    arles_agreement_num = db.Column(db.String(100), nullable=True)
    sell = db.relationship('EstateSell')

    # --- ИСПРАВЛЕНИЕ 1: ForeignKey должен указывать на 'users.id' ---
    # (потому что SalesManager использует таблицу 'users')
    deal_manager_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)

    # --- ИСПРАВЛЕНИЕ 2: Указываем 'primaryjoin' для явной связи ---
    # Мы связываем 'EstateDeal.deal_manager_id' с 'SalesManager.id'
    # (SalesManager - это класс, который смотрит на таблицу 'users')
    manager = db.relationship(
        'SalesManager',
        primaryjoin='EstateDeal.deal_manager_id == foreign(app.models.auth_models.SalesManager.id)'
    )

    __bind_key__ = 'mysql_source'


class EstateHouse(db.Model):
    __tablename__ = 'estate_houses'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    complex_name = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    geo_house = db.Column(db.String(50))

    sells = db.relationship('EstateSell', back_populates='house')
    __bind_key__ = 'mysql_source'


class EstateSell(db.Model):
    __tablename__ = 'estate_sells'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    house_id = db.Column(db.Integer, db.ForeignKey('estate_houses.id'), nullable=False)
    flatClass = db.Column(db.String(255), nullable=True)
    estate_sell_category = db.Column(db.String(100))
    estate_floor = db.Column(db.Integer)
    estate_rooms = db.Column(db.Integer)
    estate_price_m2 = db.Column(db.Float)

    estate_sell_status_name = db.Column(db.String(100), nullable=True)
    estate_price = db.Column(db.Float, nullable=True)
    estate_area = db.Column(db.Float, nullable=True)

    geo_house_entrance = db.Column(db.Integer, nullable=True)  # Подъезд
    geo_flatnum = db.Column(db.String(50), nullable=True)  # Номер помещения

    finance_operations = db.relationship('FinanceOperation', back_populates='sell', cascade="all, delete-orphan")
    house = db.relationship('EstateHouse', back_populates='sells')
    deals = db.relationship('EstateDeal', back_populates='sell', cascade="all, delete-orphan")

    __bind_key__ = 'mysql_source'