# app/core/extensions.py
import sqlite3

from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()
migrate_default = Migrate()  # Для стандартной БД (app.db)
migrate_planning = Migrate() # Для БД 'planning_db'


@event.listens_for(Engine, 'connect')
def _configure_sqlite(dbapi_connection, connection_record):
    """Готовит SQLite к записи из двух процессов.

    planning.db лежит на общем томе, и пишут в неё одновременно веб (gunicorn) и
    воркер напоминаний. В режиме по умолчанию любая параллельная запись сразу
    отдаёт «database is locked», и коммит падает.

    journal_mode=WAL разводит читателей и писателя, busy_timeout заставляет
    подождать освобождения вместо мгновенной ошибки. На MySQL-подключения не
    влияет — проверяем тип соединения.
    """
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA busy_timeout=10000')
    finally:
        cursor.close()
