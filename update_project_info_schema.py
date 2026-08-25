"""Готовит базу планирования под карточку проекта и новый вид КП.

Создает таблицы 'project_infos' / 'project_renders' и добавляет недостающие
колонки в уже существующие таблицы (УТП проекта, условия стандартной ипотеки).
Существующие данные не трогает: только CREATE TABLE IF NOT EXISTS и ADD COLUMN.
"""
import os
import sys

# Добавляем текущую директорию в путь, чтобы Python видел папку 'app'
sys.path.append(os.getcwd())

from sqlalchemy import inspect, text

from app import create_app
from app.core.extensions import db

try:
    from app.models.planning_models import (ProjectInfo, ProjectRender, CalculatorSettings,
                                            ManagerUserLink, DebtReminderSubscription)

    print("Модели успешно импортированы.")
except ImportError as e:
    print(f"ОШИБКА: Не удалось импортировать модели. Проверьте app/models/planning_models.py.\nДетали: {e}")
    sys.exit(1)

MODELS = (ProjectInfo, ProjectRender, CalculatorSettings, ManagerUserLink,
          DebtReminderSubscription)


def _sync_table(engine, inspector, table):
    """Создает таблицу или дописывает недостающие колонки."""
    if not inspector.has_table(table.name):
        table.create(bind=engine, checkfirst=True)
        print(f"  + таблица '{table.name}' создана")
        return

    existing = {col['name'] for col in inspector.get_columns(table.name)}
    missing = [col for col in table.columns if col.name not in existing]
    if not missing:
        print(f"  = таблица '{table.name}' уже актуальна")
        return

    with engine.begin() as conn:
        for column in missing:
            column_type = column.type.compile(engine.dialect)
            conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {column.name} {column_type}'))
            print(f"  + '{table.name}.{column.name}' ({column_type})")


def init_db():
    app = create_app()
    with app.app_context():
        engine = db.engines[ProjectInfo.__bind_key__]
        print(f"База планирования: {engine.url}")

        try:
            inspector = inspect(engine)
            for model in MODELS:
                _sync_table(engine, inspector, model.__table__)
            print("-" * 50)
            print("УСПЕШНО: схема обновлена.")
            print("-" * 50)
        except Exception as e:
            print(f"КРИТИЧЕСКАЯ ОШИБКА при обновлении схемы: {e}")


if __name__ == "__main__":
    init_db()
