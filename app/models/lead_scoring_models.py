# app/models/lead_scoring_models.py
"""Скоринг входящих лидов: обученные модели и выставленные оценки.

Модуль в тестовом режиме: оценки пишутся и показываются на отдельной странице,
но в работу колл-центра не попадают. Поэтому здесь же хранится всё, что нужно
для честной проверки — на каких данных модель училась, как показала себя на
отложенном периоде и какие пороги групп выбраны.

Живёт в planning_db: MySQL витрины Macro доступна только на чтение.
"""

import json

from sqlalchemy import func

from app.core.extensions import db


class LeadScoringModel(db.Model):
    """Версия обученной модели. Сама модель — файл joblib рядом с базой."""
    __bind_key__ = 'planning_db'
    __tablename__ = 'lead_scoring_models'

    id = db.Column(db.Integer, primary_key=True)
    version = db.Column(db.Integer, nullable=False, unique=True)
    # Активная модель одна: ею оцениваются новые заявки.
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    artifact_path = db.Column(db.String(500), nullable=False)

    horizon_days = db.Column(db.Integer, nullable=False)
    train_from = db.Column(db.DateTime)
    train_to = db.Column(db.DateTime)
    test_from = db.Column(db.DateTime)
    test_to = db.Column(db.DateTime)
    train_rows = db.Column(db.Integer)
    test_rows = db.Column(db.Integer)
    train_positives = db.Column(db.Integer)
    test_positives = db.Column(db.Integer)

    # Метрики и пороги — JSON: состав меняется от версии к версии, а
    # колонка на каждую цифру превратила бы модель в миграцию.
    metrics_json = db.Column(db.Text)
    grades_json = db.Column(db.Text)
    features_json = db.Column(db.Text)

    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    @property
    def metrics(self):
        return json.loads(self.metrics_json or '{}')

    @property
    def grades(self):
        return json.loads(self.grades_json or '[]')

    @property
    def features(self):
        return json.loads(self.features_json or '{}')

    def __repr__(self):
        return f'<LeadScoringModel v{self.version}>'


class LeadScore(db.Model):
    """Оценка заявки конкретной версией модели.

    Заявки, которые модель не оценивает (служебные, самоприходы, действующие
    клиенты), тоже записываются — с причиной. Иначе нельзя отличить «ещё не
    оценили» от «оценивать нечего», и воркер перебирал бы их каждый раз.
    """
    __bind_key__ = 'planning_db'
    __tablename__ = 'lead_scores'
    __table_args__ = (db.UniqueConstraint('estate_buy_id', 'model_id', name='uq_lead_score_model'),)

    id = db.Column(db.Integer, primary_key=True)
    # estate_buys.id витрины.
    estate_buy_id = db.Column(db.Integer, nullable=False, index=True)
    model_id = db.Column(db.Integer, db.ForeignKey('lead_scoring_models.id'), nullable=False, index=True)

    lead_created_at = db.Column(db.DateTime, index=True)
    score = db.Column(db.Float)
    grade = db.Column(db.String(1), index=True)
    skip_reason = db.Column(db.String(64))

    # Для страницы проверки: источник виден без похода в MySQL.
    channel_type = db.Column(db.String(32))
    utm_source = db.Column(db.String(255))

    scored_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    model = db.relationship('LeadScoringModel')

    def __repr__(self):
        return f'<LeadScore {self.estate_buy_id} {self.grade or self.skip_reason}>'
