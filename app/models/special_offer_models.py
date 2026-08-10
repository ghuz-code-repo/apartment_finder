# app/models/special_offer_models.py

from app.core.extensions import db
from sqlalchemy import func
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta


class MonthlySpecial(db.Model):
    """Модель для хранения специальных предложений 'Квартира месяца'."""
    __bind_key__ = 'planning_db'
    __tablename__ = 'monthly_specials'

    id = db.Column(db.Integer, primary_key=True)

    # ID квартиры из основной базы. Должен быть уникальным.
    sell_id = db.Column(db.Integer, nullable=False, unique=True, index=True)

    # Текст УТП от администратора
    usp_text = db.Column(db.Text, nullable=False)

    # Имя файла с планировкой (само изображение будет храниться в файловой системе)
    floor_plan_image_filename = db.Column(db.String(255), nullable=False)

    # Дополнительная скидка в процентах (например, 5.0 для 5%)
    extra_discount = db.Column(db.Float, nullable=False, default=0.0)

    # Активно ли предложение
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # Дата окончания предложения (например, 2025-07-31)
    expires_at = db.Column(db.Date, nullable=False)

    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())
    updated_at = db.Column(db.DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f'<MonthlySpecial sell_id={self.sell_id}>'

    def extend_offer(self):
        """Продлевает предложение до конца следующего месяца."""
        today = date.today()
        # Устанавливаем на конец следующего месяца
        self.expires_at = today + relativedelta(months=2) - relativedelta(days=today.day)

    @staticmethod
    def set_initial_expiry():
        """Устанавливает дату истечения на конец текущего месяца."""
        today = date.today()
        return today + relativedelta(months=1) - relativedelta(days=today.day)