from datetime import datetime
from app.core.extensions import db
from sqlalchemy import func

# --- ДОБАВЛЯЕМ ИМПОРТЫ ДЛЯ СВЯЗЕЙ ---
from . import estate_models
from . import auth_models


class ZeroMortgageMatrix(db.Model):
    # Эта модель (ZeroMortgageMatrix) в ЛОКАЛЬНОЙ базе (main_app.db)
    # У нее НЕ должно быть __bind_key__
    __tablename__ = 'zero_mortgage_matrix'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    data = db.Column(db.JSON, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<ZeroMortgageMatrix {self.name}>'


class FinanceOperation(db.Model):
    # Эта модель в УДАЛЕННОЙ базе (mysql_source)
    __tablename__ = 'finances'
    __bind_key__ = 'mysql_source'  # <-- 1. ДОБАВЛЯЕМ BIND KEY

    id = db.Column(db.Integer, primary_key=True)

    # --- 2. ИСПРАВЛЯЕМ FOREIGN KEY ---
    # Мы ссылаемся не на 'estate_sells.id', а на сам объект
    # 'estate_models.EstateSell.id', чтобы SQLAlchemy
    # мог найти таблицу в 'mysql_source' bind.
    estate_sell_id = db.Column(
        db.Integer,
        db.ForeignKey(estate_models.EstateSell.id),  # <-- Ссылка на модель
        nullable=False,
        index=True
    )

    summa = db.Column(db.Float)
    status_name = db.Column(db.String(100))
    payment_type = db.Column(db.String(100), name='types_name')
    date_added = db.Column(db.Date)
    date_to = db.Column(db.Date, nullable=True)

    # --- 3. ИСПРАВЛЯЕМ СТОЛБЕЦ ID МЕНЕДЖЕРА ---
    # Он ссылается на таблицу 'users' (которую использует SalesManager)
    manager_id = db.Column(
        db.Integer,
        db.ForeignKey(auth_models.SalesManager.id),  # <-- Ссылка на модель
        name='respons_manager_id',  # <-- Используем ОРИГИНАЛЬНОЕ имя столбца в MySQL
        index=True
    )

    # --- 4. ИСПРАВЛЯЕМ СВЯЗИ ---
    sell = db.relationship('EstateSell', back_populates='finance_operations')  # <-- Добавляем back_populates

    # --- 5. ДОБАВЛЯЕМ СВЯЗЬ С МЕНЕДЖЕРОМ ---
    manager = db.relationship(
        'SalesManager',
        primaryjoin='foreign(FinanceOperation.manager_id) == app.models.auth_models.SalesManager.id'
    )

class DailyCurrencyRate(db.Model):
    """Таблица исторических курсов валют."""
    __tablename__ = 'daily_currency_rates'
    date = db.Column(db.Date, primary_key=True)
    rate = db.Column(db.Float, nullable=False)

    def __repr__(self):
        return f'<DailyRate {self.date}: {self.rate}>'
class CurrencySettings(db.Model):
    # Эта модель в ЛОКАЛЬНОЙ базе (main_app.db)
    __tablename__ = 'currency_settings'
    id = db.Column(db.Integer, primary_key=True)
    rate_source = db.Column(db.String(10), default='cbu', nullable=False)
    cbu_rate = db.Column(db.Float, default=0.0)
    manual_rate = db.Column(db.Float, default=0.0)
    effective_rate = db.Column(db.Float, default=0.0)
    cbu_last_updated = db.Column(db.DateTime)
    use_historical_rate = db.Column(db.Boolean, default=False, nullable=False)
    def update_effective_rate(self):
        if self.rate_source == 'cbu':
            self.effective_rate = self.cbu_rate
        else:
            self.effective_rate = self.manual_rate


class ProjectObligation(db.Model):
    # Эта модель в 'planning_db' (у нее есть __bind_key__)
    __tablename__ = 'project_obligations'
    __bind_key__ = 'planning_db'

    id = db.Column(db.Integer, primary_key=True)
    project_name = db.Column(db.String(255), nullable=False, index=True)
    obligation_type = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), nullable=False, default='UZS')
    due_date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(50), default='Ожидает оплаты')
    payment_date = db.Column(db.Date, nullable=True)
    comment = db.Column(db.Text, nullable=True)
    property_type = db.Column(db.String(100), nullable=True, index=True)
    __table_args__ = (
        db.UniqueConstraint('project_name', 'property_type', 'currency', name='_project_prop_currency_uc'),
    )

    def __repr__(self):
        return f'<ProjectObligation {self.project_name} ({self.property_type}) - {self.amount}>'