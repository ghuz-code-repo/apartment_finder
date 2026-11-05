# app/models/competitor_models.py
from datetime import datetime
from app.core.extensions import db


class Competitor(db.Model):
    __tablename__ = 'competitors'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    is_internal = db.Column(db.Boolean, default=False) # Флаг внутреннего проекта
    description = db.Column(db.Text)
    # Координаты
    lat = db.Column(db.Float, nullable=True)
    lng = db.Column(db.Float, nullable=True)

    # Характеристики
    property_class = db.Column(db.String(100))
    property_type = db.Column(db.String(100))  # квартиры, коммерция, парковки, кладовки
    ceiling_height = db.Column(db.Float)
    amenities = db.Column(db.Text)  # Список через запятую

    # Привязка к нашим проектам (названия из MySQL)
    direct_competitor_name = db.Column(db.String(255))
    indirect_competitor_name = db.Column(db.String(255))

    # Аналитические показатели
    construction_stage = db.Column(db.String(100))
    units_count = db.Column(db.Integer)
    sold_count = db.Column(db.Integer, default=0) # Продано шт
    avg_area = db.Column(db.Float)
    avg_price_sqm = db.Column(db.Float) # Средняя цена за квадратный метр остатка
    avg_bottom_price = db.Column(db.Float) # Средняя стоимость дна остатков

    # Сроки
    planned_cadastre_date = db.Column(db.Date)
    initial_cadastre_date = db.Column(db.Date)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


    media = db.relationship('CompetitorMedia', backref='competitor', lazy='joined', cascade='all, delete-orphan')

    # «Средняя стоимость дна остатков» у конкурентов приходит из Excel как
    # стоимость одного объекта ($ за квартиру), а у наших ЖК считается из MySQL
    # в $/м². Сравнивать их напрямую нельзя — приводим к общему виду здесь.
    @property
    def bottom_price_sqm(self):
        """Цена дна за м², $."""
        if self.avg_bottom_price is None:
            return None
        if self.is_internal:
            return self.avg_bottom_price
        if not self.avg_area:
            return None
        return self.avg_bottom_price / self.avg_area

    @property
    def bottom_price_unit(self):
        """Цена дна за объект, $."""
        if self.avg_bottom_price is None:
            return None
        if not self.is_internal:
            return self.avg_bottom_price
        if not self.avg_area:
            return None
        return self.avg_bottom_price * self.avg_area

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'lat': self.lat,
            'lng': self.lng,
            'property_class': self.property_class,
            'property_type': self.property_type,
            'avg_price_sqm': self.avg_price_sqm,
            'avg_bottom_price': self.avg_bottom_price,
            'is_internal': self.is_internal,
            'direct_competitor': self.direct_competitor_name
        }


class CompetitorHistory(db.Model):
    __tablename__ = 'competitor_history'

    id = db.Column(db.Integer, primary_key=True)
    competitor_id = db.Column(db.Integer, db.ForeignKey('competitors.id'), nullable=False)

    # Снимок данных на момент записи
    avg_price_sqm = db.Column(db.Float)
    avg_bottom_price = db.Column(db.Float)
    units_count = db.Column(db.Integer)
    sold_count = db.Column(db.Integer)

    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)

    competitor = db.relationship('Competitor', backref=db.backref('history', lazy='dynamic'))
class CompetitorMedia(db.Model):
    __tablename__ = 'competitor_media'
    id = db.Column(db.Integer, primary_key=True)
    competitor_id = db.Column(db.Integer, db.ForeignKey('competitors.id'), nullable=False)
    file_path = db.Column(db.String(512), nullable=False)
    media_type = db.Column(db.String(50))  # image, video, document