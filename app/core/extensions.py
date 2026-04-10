# app/core/extensions.py
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
migrate_default = Migrate()  # Для стандартной БД (app.db)
migrate_planning = Migrate() # Для БД 'planning_db'