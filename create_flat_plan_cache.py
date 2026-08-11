"""Создаёт таблицу кэша планировок flat_plan_cache в planning_db.

Одна таблица, поэтому обходимся точечным созданием, не трогая alembic:
существующие данные не затрагиваются, повторный запуск безопасен.

Запуск:  python create_flat_plan_cache.py
"""
import os
import sys

sys.path.append(os.getcwd())

from app import create_app
from app.core.extensions import db
from app.models.planning_models import FlatPlanCache


def init_db():
    app = create_app()
    with app.app_context():
        engine = db.engines['planning_db']
        print(f'Подключение к planning_db: {engine.url}')
        FlatPlanCache.__table__.create(engine, checkfirst=True)
        print("УСПЕШНО: таблица 'flat_plan_cache' создана (или уже существовала).")


if __name__ == '__main__':
    init_db()
