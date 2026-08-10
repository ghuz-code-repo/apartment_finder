from app.core.extensions import db
from sqlalchemy import func

class SyncLog(db.Model):
    """
    Модель для хранения времени последней успешной синхронизации данных.
    """
    __tablename__ = 'sync_log'
    id = db.Column(db.Integer, primary_key=True)
    last_sync_timestamp = db.Column(db.DateTime, server_default=func.now(), nullable=False)
    status = db.Column(db.String(50), nullable=False, default='success') # 'success', 'failed'
    details = db.Column(db.Text, nullable=True) # Дополнительная информация или текст ошибки

    def __repr__(self):
        return f'<SyncLog {self.last_sync_timestamp} [{self.status}]>'