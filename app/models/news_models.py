from datetime import datetime
from app.core.extensions import db
from datetime import datetime, timedelta

class News(db.Model):
    __tablename__ = 'market_news'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    media = db.relationship('NewsMedia', backref='news', cascade='all, delete-orphan', lazy='joined')

    @property
    def tashkent_time(self):
        """Возвращает время создания с поправкой +5 часов для Ташкента."""
        return self.created_at + timedelta(hours=5)


class NewsMedia(db.Model):
    __tablename__ = 'news_media'
    id = db.Column(db.Integer, primary_key=True)
    news_id = db.Column(db.Integer, db.ForeignKey('market_news.id'), nullable=False)
    file_path = db.Column(db.String(512), nullable=False)
    media_type = db.Column(db.String(50))  # 'image' или 'video'