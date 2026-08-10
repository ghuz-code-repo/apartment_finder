from ..core.extensions import db

def get_mysql_session():
    """
    Возвращает СТАНДАРТНУЮ сессию.
    Модели с __bind_key__ = 'mysql_source' сами выберут этот bind.
    """
    return db.session

def get_planning_session():
    """
    Возвращает СТАНДАРТНУЮ сессию.
    Модели с __bind_key__ = 'planning_db' сами выберут этот bind.
    """
    return db.session

def get_default_session():
    """Возвращает сессию по умолчанию (main_app.db)."""
    return db.session