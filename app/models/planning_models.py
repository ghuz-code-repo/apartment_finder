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


class FlatPlanCache(db.Model):
    """Ответ Macro API по планировке квартиры.

    Лимит Macro — 100 запросов в минуту на ключ, а карточку объекта менеджеры
    открывают пачками, поэтому ответ храним у себя и обновляем по TTL.
    Неудачный запрос тоже сохраняется (files пустой): это не даёт долбить
    чужой сервер на каждом обновлении страницы.
    """
    __bind_key__ = 'planning_db'
    __tablename__ = 'flat_plan_cache'

    estate_id = db.Column(db.Integer, primary_key=True)
    plan_name = db.Column(db.String(255), nullable=True)
    files_json = db.Column(db.Text, nullable=False, default='[]')
    error = db.Column(db.String(500), nullable=True)
    fetched_at = db.Column(db.DateTime(timezone=True), server_default=func.now())


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
    # Условия стандартной ипотеки — нужны для расчета ежемесячного взноса в КП.
    # Пока не задан срок, взнос в документе не показывается.
    # mortgage_rate_annual — ставка до кадастра, после кадастра действует
    # mortgage_rate_after_cadastre (если она не задана, ставка не меняется).
    mortgage_rate_annual = db.Column(db.Float, default=0.0)
    mortgage_rate_after_cadastre = db.Column(db.Float, default=0.0)
    mortgage_term_months = db.Column(db.Integer, default=0)

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
        primaryjoin='foreign(ManagerSalesPlan.manager_id) == app.models.auth_models.SalesManager.id',
        back_populates='plans',
        viewonly=True,
        overlaps='manager,plans'
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


# Поля карточки ЖК, у которых есть переводы. Имена собственные (застройщик,
# бюро) и числа не переводятся, поэтому в список не входят.
PROJECT_INFO_TRANSLATABLE_FIELDS = (
    'project_class',
    'location',
    'construction_tech',
    'facade_materials',
    'parking',
    'infrastructure',
    'concept',
    'description',
    'usp',
)
PROJECT_INFO_EXTRA_LANGS = ('uz', 'en')


class ManagerUserLink(db.Model):
    """Связка пользователя системы с менеджером в CRM.

    Пользователи живут в шлюзе, менеджеры — в MySQL Macro, общего идентификатора
    у них нет. По умолчанию сопоставляем по ФИО, а тёзок и расхождения в написании
    админ разводит руками на странице связок — тогда запись появляется здесь.
    """
    __bind_key__ = 'planning_db'
    __tablename__ = 'manager_user_links'

    # Логин из шлюза — он же ключ: у одного пользователя один менеджер.
    username = db.Column(db.String(255), primary_key=True)
    manager_id = db.Column(db.Integer, nullable=False, index=True)
    # ФИО на момент связывания — чтобы админ видел, кого связали, без похода в CRM.
    full_name = db.Column(db.String(255), nullable=True)

    updated_at = db.Column(db.DateTime(timezone=True), onupdate=func.now())
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f'<ManagerUserLink {self.username} -> {self.manager_id}>'


class DebtReminderSubscription(db.Model):
    """Подписка менеджера на напоминания о дебиторке.

    Само сообщение отправляет бот-нотификатор портала. Резолв получателя идёт
    по telegram-нику, а не по логину на портале, поэтому ник менеджер указывает
    здесь сам; сам чат привязывается в личном кабинете портала.
    """
    __bind_key__ = 'planning_db'
    __tablename__ = 'debt_reminder_subscriptions'

    username = db.Column(db.String(255), primary_key=True)
    manager_id = db.Column(db.Integer, nullable=True, index=True)
    # Итог последней отправки: 'ok' либо машинный код отказа от
    # notification-service. Заранее узнать, привязан ли Telegram, сервис не
    # может — резолв живёт в шлюзе, поэтому вкладка показывает именно результат.
    last_status = db.Column(db.String(64), nullable=True)
    last_error = db.Column(db.String(500), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=False)
    # Как часто напоминать: 'day' — раз в сутки, 'hour' — раз в час.
    interval = db.Column(db.String(16), nullable=False, default='day')
    # Час отправки для ежедневного режима, по времени сервера.
    notify_hour = db.Column(db.Integer, nullable=False, default=9)
    # Когда последний раз отправляли. Дата нужна для дневного режима, время —
    # для часового; храним оба, чтобы смена интервала не путала счёт.
    last_sent_date = db.Column(db.Date, nullable=True)
    last_sent_at = db.Column(db.DateTime, nullable=True)

    updated_at = db.Column(db.DateTime(timezone=True), onupdate=func.now())
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f'<DebtReminderSubscription {self.username} active={self.is_active}>'


class ProjectInfo(db.Model):
    """
    Маркетинговая карточка ЖК: описание концепции и характеристики проекта.
    Заполняется вручную на странице "Настройки информации о проекте".
    """
    __bind_key__ = 'planning_db'
    __tablename__ = 'project_infos'

    # Название ЖК является первичным ключом (как и в ProjectPassport)
    complex_name = db.Column(db.String(255), primary_key=True)

    # Общее
    project_class = db.Column(db.String(100), nullable=True)  # Бизнес-класс, комфорт-класс и т.д.
    developer = db.Column(db.String(255), nullable=True)  # Застройщик
    architect_bureau = db.Column(db.String(255), nullable=True)  # Архитектурное бюро
    location = db.Column(db.String(500), nullable=True)  # Район / расположение
    website_url = db.Column(db.String(1000), nullable=True)  # Сайт проекта

    # Характеристики застройки
    buildings_count = db.Column(db.Integer, nullable=True)  # Количество корпусов
    floors_min = db.Column(db.Integer, nullable=True)  # Этажность, от
    floors_max = db.Column(db.Integer, nullable=True)  # Этажность, до
    ceiling_height = db.Column(db.Float, nullable=True)  # Высота потолков, м
    area_min = db.Column(db.Float, nullable=True)  # Площадь квартир, от м²
    area_max = db.Column(db.Float, nullable=True)  # Площадь квартир, до м²

    # Технические характеристики
    construction_tech = db.Column(db.Text, nullable=True)  # Конструктив / технология строительства
    facade_materials = db.Column(db.Text, nullable=True)  # Отделка фасадов
    parking = db.Column(db.Text, nullable=True)  # Паркинг
    infrastructure = db.Column(db.Text, nullable=True)  # Инфраструктура и благоустройство

    # Тексты
    concept = db.Column(db.Text, nullable=True)  # Краткая концепция / позиционирование
    description = db.Column(db.Text, nullable=True)  # Полное описание проекта
    usp = db.Column(db.Text, nullable=True)  # УТП проекта: по одному пункту на строку

    # --- Переводы для КП ---
    # Русский текст лежит в основных полях выше, здесь узбекский и английский.
    # Незаполненный перевод в документе подменяется русским, чтобы КП не зияло дырами.
    project_class_uz = db.Column(db.String(100), nullable=True)
    project_class_en = db.Column(db.String(100), nullable=True)
    location_uz = db.Column(db.String(500), nullable=True)
    location_en = db.Column(db.String(500), nullable=True)
    construction_tech_uz = db.Column(db.Text, nullable=True)
    construction_tech_en = db.Column(db.Text, nullable=True)
    facade_materials_uz = db.Column(db.Text, nullable=True)
    facade_materials_en = db.Column(db.Text, nullable=True)
    parking_uz = db.Column(db.Text, nullable=True)
    parking_en = db.Column(db.Text, nullable=True)
    infrastructure_uz = db.Column(db.Text, nullable=True)
    infrastructure_en = db.Column(db.Text, nullable=True)
    concept_uz = db.Column(db.Text, nullable=True)
    concept_en = db.Column(db.Text, nullable=True)
    description_uz = db.Column(db.Text, nullable=True)
    description_en = db.Column(db.Text, nullable=True)
    usp_uz = db.Column(db.Text, nullable=True)
    usp_en = db.Column(db.Text, nullable=True)

    renders = db.relationship('ProjectRender', backref='info', lazy='select',
                              cascade='all, delete-orphan',
                              order_by='ProjectRender.sort_order.asc(), ProjectRender.id.asc()')

    # Системные поля
    updated_at = db.Column(db.DateTime(timezone=True), onupdate=func.now())
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f'<ProjectInfo {self.complex_name}>'

    def localized(self, field, lang=None):
        """Значение поля на нужном языке с откатом на русский.

        Русский — базовый: менеджер обязан заполнить его, переводы
        необязательны, и пустой перевод не должен оставлять в КП пустое место.
        """
        base = getattr(self, field, None)
        if not lang or lang == 'ru' or field not in PROJECT_INFO_TRANSLATABLE_FIELDS:
            return base
        return getattr(self, f'{field}_{lang}', None) or base

    @staticmethod
    def _split_usp(text):
        if not text:
            return []
        return [line.strip(' -•') for line in text.splitlines() if line.strip(' -•')]

    def usp_items_for(self, lang=None):
        """УТП построчно на нужном языке: в КП каждый пункт идёт буллитом."""
        return self._split_usp(self.localized('usp', lang))

    @property
    def usp_items(self):
        """УТП на русском — язык по умолчанию."""
        return self._split_usp(self.usp)

    def to_dict(self):
        """Возвращает данные в виде словаря для API."""
        return {
            'complex_name': self.complex_name,
            'project_class': self.project_class,
            'developer': self.developer,
            'architect_bureau': self.architect_bureau,
            'location': self.location,
            'website_url': self.website_url,
            'buildings_count': self.buildings_count,
            'floors_min': self.floors_min,
            'floors_max': self.floors_max,
            'ceiling_height': self.ceiling_height,
            'area_min': self.area_min,
            'area_max': self.area_max,
            'construction_tech': self.construction_tech,
            'facade_materials': self.facade_materials,
            'parking': self.parking,
            'infrastructure': self.infrastructure,
            'concept': self.concept,
            'description': self.description,
            'usp': self.usp,
            'usp_items': self.usp_items,
            'renders': [r.to_dict() for r in self.renders],
        }


class ProjectRender(db.Model):
    """
    Рендер (визуализация) ЖК. На один проект допускается не более 5 штук.
    """
    __bind_key__ = 'planning_db'
    __tablename__ = 'project_renders'

    id = db.Column(db.Integer, primary_key=True)
    complex_name = db.Column(db.String(255),
                             db.ForeignKey('project_infos.complex_name', ondelete='CASCADE'),
                             nullable=False, index=True)

    filename = db.Column(db.String(255), nullable=False)  # Имя файла внутри static/uploads/project_renders
    title = db.Column(db.String(255), nullable=True)  # Подпись к рендеру
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    # Размеры сохраненного файла: по ним проверяется пригодность рендера для КП.
    width = db.Column(db.Integer, nullable=True)
    height = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f'<ProjectRender {self.id} for {self.complex_name}>'

    def to_dict(self):
        """Возвращает данные в виде словаря для API."""
        return {
            'id': self.id,
            'complex_name': self.complex_name,
            'filename': self.filename,
            'title': self.title,
            'sort_order': self.sort_order,
            'width': self.width,
            'height': self.height,
        }