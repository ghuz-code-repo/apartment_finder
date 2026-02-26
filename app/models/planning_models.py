# app/models/planning_models.py

from app.core.extensions import db
from sqlalchemy import Enum as SQLAlchemyEnum, func, UniqueConstraint
from . import auth_models
import enum


class PropertyType(enum.Enum):
    FLAT = 'Квартира'
    COMM = 'Коммерческое помещение'
    GARAGE = 'Парковка'
    STORAGEROOM = 'Кладовое помещение'


class ProjectFinancialTarget(db.Model):
    """Глобальные финансовые цели ЖК"""
    __bind_key__ = 'planning_db'
    __tablename__ = 'project_financial_targets'

    complex_name = db.Column(db.String(255), db.ForeignKey('project_passports.complex_name'), primary_key=True)
    total_construction_budget = db.Column(db.Float, nullable=False, default=0.0)
    target_margin_percent = db.Column(db.Float, nullable=False, default=20.0)
    estimated_other_costs = db.Column(db.Float, nullable=False, default=0.0)

    updated_at = db.Column(db.DateTime(timezone=True), onupdate=func.now())


class MonthlyCostPlan(db.Model):
    """Помесячный план расходов на строительство"""
    __bind_key__ = 'planning_db'
    __tablename__ = 'monthly_cost_plans'

    id = db.Column(db.Integer, primary_key=True)
    complex_name = db.Column(db.String(255), db.ForeignKey('project_passports.complex_name'), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    planned_spending = db.Column(db.Float, nullable=False, default=0.0)

    __table_args__ = (
        db.UniqueConstraint('complex_name', 'year', 'month', name='_complex_month_cost_uc'),
    )

class ProjectCompetitor(db.Model):
    """
    Модель для хранения данных по конкурентам для
    сравнительной таблицы в "Паспорте проекта".
    """
    __bind_key__ = 'planning_db'
    __tablename__ = 'project_competitors'

    id = db.Column(db.Integer, primary_key=True)

    # Внешний ключ, ссылающийся на 'project_passports.complex_name'
    passport_complex_name = db.Column(db.String(255),
                                      db.ForeignKey('project_passports.complex_name', ondelete='CASCADE'),
                                      nullable=False, index=True)

    # Поля из ТЗ
    competitor_name = db.Column(db.String(500), nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    project_class = db.Column(db.String(100), nullable=True)
    remainders_units = db.Column(db.Integer, nullable=True)
    total_units = db.Column(db.Integer, nullable=True)
    mortgage_types = db.Column(db.String(500), nullable=True)
    has_underground_parking = db.Column(db.Boolean, nullable=True)
    has_fitness = db.Column(db.Boolean, nullable=True)
    has_ground_floor_commercial = db.Column(db.Boolean, nullable=True)
    ceiling_height = db.Column(db.Float, nullable=True)
    construction_type = db.Column(db.String(500), nullable=True)
    planned_completion_date = db.Column(db.Date, nullable=True)
    construction_stage = db.Column(db.String(500), nullable=True)
    price_per_sqm = db.Column(db.Float, nullable=True)
    sales_pace = db.Column(db.Float, nullable=True)
    facade_material = db.Column(db.String(500), nullable=True)
    avg_area = db.Column(db.Float, nullable=True)

    # Системное поле для сортировки
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f'<ProjectCompetitor {self.competitor_name} for {self.passport_complex_name}>'

    def to_dict(self):
        """Возвращает данные в виде словаря для API или шаблонов."""
        return {
            'id': self.id,
            'passport_complex_name': self.passport_complex_name,
            'competitor_name': self.competitor_name,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'project_class': self.project_class,
            'remainders_units': self.remainders_units,
            'total_units': self.total_units,
            'mortgage_types': self.mortgage_types,
            'has_underground_parking': self.has_underground_parking,
            'has_fitness': self.has_fitness,
            'has_ground_floor_commercial': self.has_ground_floor_commercial,
            'ceiling_height': self.ceiling_height,
            'construction_type': self.construction_type,
            'planned_completion_date': self.planned_completion_date.isoformat() if self.planned_completion_date else None,
            'construction_stage': self.construction_stage,
            'price_per_sqm': self.price_per_sqm,
            'sales_pace': self.sales_pace,
            'facade_material': self.facade_material,
            'avg_area': self.avg_area,
        }

class PaymentMethod(enum.Enum):
    FULL_PAYMENT = '100% оплата'
    MORTGAGE = 'Ипотека'


class DiscountVersion(db.Model):
    __bind_key__ = 'planning_db'
    __tablename__ = 'discount_versions'
    id = db.Column(db.Integer, primary_key=True)
    version_number = db.Column(db.Integer, nullable=False, unique=True)
    comment = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())
    was_ever_activated = db.Column(db.Boolean, default=False, nullable=False)
    changes_summary_json = db.Column(db.Text, nullable=True)
    summary_sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    discounts = db.relationship('Discount', back_populates='version', cascade="all, delete-orphan")
    complex_comments = db.relationship('ComplexComment', back_populates='version', cascade="all, delete-orphan")


class SalesPlan(db.Model):
    __bind_key__ = 'planning_db'
    __tablename__ = 'sales_plans'
    id = db.Column(db.Integer, primary_key=True)
    complex_name = db.Column(db.String(255), nullable=False, index=True)
    property_type = db.Column(db.String(100), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    plan_units = db.Column(db.Integer, nullable=False, default=0)
    plan_volume = db.Column(db.Float, nullable=False, default=0.0)
    plan_income = db.Column(db.Float, nullable=False, default=0.0)
    __table_args__ = (
        db.UniqueConstraint('year', 'month', 'complex_name', 'property_type', name='_plan_period_complex_prop_uc'),
    )


class Discount(db.Model):
    __bind_key__ = 'planning_db'
    __tablename__ = 'discounts'
    id = db.Column(db.Integer, primary_key=True)
    version_id = db.Column(db.Integer, db.ForeignKey('discount_versions.id'), nullable=False, index=True)
    complex_name = db.Column(db.String(255), nullable=False, index=True)
    property_type = db.Column(SQLAlchemyEnum(PropertyType), nullable=False)
    payment_method = db.Column(SQLAlchemyEnum(PaymentMethod), nullable=False)
    mpp = db.Column(db.Float, default=0.0)
    rop = db.Column(db.Float, default=0.0)
    kd = db.Column(db.Float, default=0.0)
    opt = db.Column(db.Float, default=0.0)
    gd = db.Column(db.Float, default=0.0)
    holding = db.Column(db.Float, default=0.0)
    shareholder = db.Column(db.Float, default=0.0)
    action = db.Column(db.Float, default=0.0)
    cadastre_date = db.Column(db.Date, nullable=True)
    version = db.relationship('DiscountVersion', back_populates='discounts')
    __table_args__ = (
        db.UniqueConstraint('version_id', 'complex_name', 'property_type', 'payment_method',
                            name='_version_complex_prop_payment_uc'),
    )


class ComplexComment(db.Model):
    __bind_key__ = 'planning_db'
    __tablename__ = 'complex_comments'
    id = db.Column(db.Integer, primary_key=True)
    version_id = db.Column(db.Integer, db.ForeignKey('discount_versions.id'), nullable=False)
    complex_name = db.Column(db.String(255), nullable=False, index=True)
    comment = db.Column(db.Text, nullable=True)
    version = db.relationship('DiscountVersion', back_populates='complex_comments')
    __table_args__ = (
        db.UniqueConstraint('version_id', 'complex_name', name='_version_complex_uc'),
    )

class ZeroMortgageMatrix(db.Model):
    __bind_key__ = 'planning_db'
    __tablename__ = 'zero_mortgage_matrix'
    id = db.Column(db.Integer, primary_key=True)
    term_months = db.Column(db.Integer, nullable=False)
    dp_percent = db.Column(db.Integer, nullable=False)
    cashback_percent = db.Column(db.Float, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('term_months', 'dp_percent', name='_term_dp_uc'),
    )
class CalculatorSettings(db.Model):
    __bind_key__ = 'planning_db'
    __tablename__ = 'calculator_settings'
    id = db.Column(db.Integer, primary_key=True)
    standard_installment_whitelist = db.Column(db.Text, nullable=True)
    dp_installment_whitelist = db.Column(db.Text, nullable=True)
    dp_installment_max_term = db.Column(db.Integer, default=6)
    time_value_rate_annual = db.Column(db.Float, default=16.5)
    standard_installment_min_dp_percent = db.Column(db.Float, default=15.0)
    zero_mortgage_whitelist = db.Column(db.Text, nullable=True)

class ManagerSalesPlan(db.Model):
    __bind_key__ = 'planning_db'
    __tablename__ = 'manager_sales_plans'

    id = db.Column(db.Integer, primary_key=True)
    manager_id = db.Column(db.Integer, nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    plan_volume = db.Column(db.Float, nullable=False, default=0.0)
    plan_income = db.Column(db.Float, nullable=False, default=0.0)
    manager = db.relationship(
        'app.models.auth_models.SalesManager',
        primaryjoin='ManagerSalesPlan.manager_id == foreign(app.models.auth_models.SalesManager.id)',
        backref='sales_plans'
    )

    __table_args__ = (
        db.UniqueConstraint('manager_id', 'year', 'month', name='_manager_plan_period_uc'),
    )

# --- НОВЫЕ ФУНКЦИИ-"ПЕРЕВОДЧИКИ" ---

def map_russian_to_mysql_key(russian_value: str) -> str:
    """
    Переводит русское название типа ('Квартира') в ключ MySQL ('flat').
    """
    mapping = {
        'Квартира': 'flat',
        'Коммерческое помещение': 'comm',
        'Парковка': 'garage',
        'Кладовое помещение': 'storageroom'
    }
    # Возвращаем ключ, если он есть в словаре, или само значение (на всякий случай)
    return mapping.get(russian_value, russian_value)

def map_mysql_key_to_russian_value(mysql_key: str) -> str:
    """
    Переводит ключ MySQL ('flat') в русское название ('Квартира').
    """
    mapping = {
        'flat': 'Квартира',
        'comm': 'Коммерческое помещение',
        'garage': 'Парковка',
        'storageroom': 'Кладовое помещение'
    }
    # Возвращаем русское значение, если оно есть, или сам ключ
    return mapping.get(mysql_key, mysql_key)


class ProjectPassport(db.Model):
    """
    Модель для хранения статических, редактируемых данных
    для страницы "Паспорт проекта".
    """
    __bind_key__ = 'planning_db'
    __tablename__ = 'project_passports'

    # Название ЖК является первичным ключом
    complex_name = db.Column(db.String(255), primary_key=True)

    # Редактируемые поля
    construction_type = db.Column(db.String(500), nullable=True)
    address_link = db.Column(db.String(1000), nullable=True)  # Для интерактивной карты
    heating_type = db.Column(db.String(500), nullable=True)
    finishing_type = db.Column(db.String(500), nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    current_stage = db.Column(db.String(1000), nullable=True)
    project_manager = db.Column(db.String(255), nullable=True)
    chief_engineer = db.Column(db.String(255), nullable=True)
    sales_manager = db.Column(db.String(255), nullable=True)
    planned_sales_pace = db.Column(db.Float, nullable=True)
    construction_stages = db.relationship('ProjectConstructionStage', backref='passport', lazy='dynamic',
                                          cascade="all, delete-orphan", order_by='ProjectConstructionStage.start_date')
    competitors = db.relationship('ProjectCompetitor', backref='passport',
                                  cascade="all, delete-orphan",
                                  order_by='ProjectCompetitor.id.asc()')
    # Системные поля
    updated_at = db.Column(db.DateTime(timezone=True), onupdate=func.now())
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f'<ProjectPassport {self.complex_name}>'

    def to_dict(self):
        """Возвращает данные в виде словаря для API."""
        return {
            'complex_name': self.complex_name,
            'construction_type': self.construction_type,
            'address_link': self.address_link,
            'heating_type': self.heating_type,
            'finishing_type': self.finishing_type,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'current_stage': self.current_stage,
            'project_manager': self.project_manager,
            'chief_engineer': self.chief_engineer,
            'sales_manager': self.sales_manager,
            'planned_sales_pace': self.planned_sales_pace,
        }


class ProjectConstructionStage(db.Model):
    """
    Модель для хранения этапов строительства по каждому проекту.
    """
    __bind_key__ = 'planning_db'
    __tablename__ = 'project_construction_stages'

    id = db.Column(db.Integer, primary_key=True)

    # Внешний ключ, ссылающийся на 'project_passports.complex_name'
    complex_name = db.Column(db.String(255), db.ForeignKey('project_passports.complex_name'), nullable=False,
                             index=True)

    # Редактируемые поля
    stage_name = db.Column(db.String(500), nullable=False)
    start_date = db.Column(db.Date, nullable=True)
    planned_end_date = db.Column(db.Date, nullable=True)
    actual_end_date = db.Column(db.Date, nullable=True)

    # Системные поля
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f'<ProjectConstructionStage {self.id} for {self.complex_name}>'

    def to_dict(self):
        """Возвращает данные в виде словаря для API."""
        return {
            'id': self.id,
            'complex_name': self.complex_name,
            'stage_name': self.stage_name,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'planned_end_date': self.planned_end_date.isoformat() if self.planned_end_date else None,
            'actual_end_date': self.actual_end_date.isoformat() if self.actual_end_date else None,
        }